"""工具系统（design §6）：注册表 + http_request（lessons 3.7 前置校验链）。"""

import httpx
import pytest

import app.tools as tools_module
from app.tools import get_tool_definitions, run_tool
from app.tools.registry import ToolError


def test_registry_has_http_request_and_sorted():
    defs = get_tool_definitions()
    names = [d["name"] for d in defs]
    assert names == sorted(names)  # 顺序稳定（lessons 3.2，缓存友好）
    assert "http_request" in names
    d = next(x for x in defs if x["name"] == "http_request")
    assert d["input_schema"]["type"] == "object"
    assert "url" in d["input_schema"]["properties"]
    assert "description" in d


class TestHttpRequestValidation:
    """前置校验链（lessons 3.7）：构造期拒绝，不发网络请求。"""

    async def _run(self, url: str):
        return await run_tool("http_request", {"url": url})

    @pytest.mark.anyio
    async def test_rejects_url_over_2000_chars(self):
        with pytest.raises(ToolError, match="URL 过长"):
            await self._run("https://x.example/" + "a" * 2000)

    @pytest.mark.anyio
    async def test_rejects_embedded_credentials(self):
        with pytest.raises(ToolError, match="凭据"):
            await self._run("https://user:pass@example.com/api")

    @pytest.mark.anyio
    async def test_rejects_domain_without_dot(self):
        with pytest.raises(ToolError, match="域名"):
            await self._run("http://localhost/api")

    @pytest.mark.anyio
    async def test_rejects_non_http_scheme(self):
        with pytest.raises(ToolError):
            await self._run("file:///etc/passwd")

    @pytest.mark.anyio
    async def test_rejects_empty_url(self):
        with pytest.raises(ToolError):
            await self._run("")


class TestHttpRequestExecution:
    def _transport(self, handler):  # type: ignore[no-untyped-def]
        return httpx.MockTransport(handler)

    @pytest.mark.anyio
    async def test_get_returns_status_and_body(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            return httpx.Response(200, text='{"ok": 1}')

        monkeypatch.setattr(tools_module.http_request, "_TRANSPORT", self._transport(handler))
        result = await run_tool("http_request", {"url": "https://api.example.com/data"})
        assert "200" in result
        assert '{"ok": 1}' in result

    @pytest.mark.anyio
    async def test_post_with_body(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert json.loads(request.content) == {"q": "hi"}
            return httpx.Response(200, text="ok")

        import json

        monkeypatch.setattr(tools_module.http_request, "_TRANSPORT", self._transport(handler))
        result = await run_tool(
            "http_request",
            {"url": "https://api.example.com/search", "method": "POST", "body": {"q": "hi"}},
        )
        assert "200" in result

    @pytest.mark.anyio
    async def test_body_truncated_with_tail_note(self, monkeypatch):
        big = "x" * 200_000

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=big)

        monkeypatch.setattr(tools_module.http_request, "_TRANSPORT", self._transport(handler))
        result = await run_tool("http_request", {"url": "https://api.example.com/big"})
        assert len(result) < 200_000
        assert "截断" in result  # 尾注明示，不静默砍（lessons 3.4）

    @pytest.mark.anyio
    async def test_http_error_status_returned_not_raised(self, monkeypatch):
        """HTTP 错误码不是工具异常——作为结果交给模型自己决定（design §5.8）。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="not found")

        monkeypatch.setattr(tools_module.http_request, "_TRANSPORT", self._transport(handler))
        result = await run_tool("http_request", {"url": "https://api.example.com/missing"})
        assert "404" in result

    @pytest.mark.anyio
    async def test_cross_domain_redirect_chain_visible(self, monkeypatch):
        """跨域跳转不静默跟随——完整跳转链写进结果（lessons 3.7 变通）。"""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "a.example.com":
                return httpx.Response(302, headers={"location": "https://b.example.com/final"})
            return httpx.Response(200, text="landed")

        # 禁用自动跟随，手动实现重定向循环上限 10 跳
        monkeypatch.setattr(
            tools_module.http_request, "_TRANSPORT", self._transport(handler)
        )
        result = await run_tool("http_request", {"url": "https://a.example.com/start"})
        assert "b.example.com" in result  # 跳转目标可见
        assert "landed" in result

    @pytest.mark.anyio
    async def test_unknown_tool_raises(self):
        with pytest.raises(ToolError):
            await run_tool("no_such_tool", {})
