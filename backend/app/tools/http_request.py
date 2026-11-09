"""http_request 工具（design §6.2(1)，lessons 3.7 前置校验链）。

不带任何凭据的普通 HTTP 请求，给 Agent 查公开信息用。
凭据调用是 use_credential 的事（P2-3），此处刻意不做。
"""

from typing import Any
from urllib.parse import urlparse

import httpx

from app.tools.registry import Tool, ToolError

# 测试注入点：monkeypatch 成 httpx.MockTransport，不打真网
_TRANSPORT: httpx.AsyncBaseTransport | None = None

_MAX_URL_LEN = 2000
_TIMEOUT_S = 60.0
_MAX_REDIRECTS = 10
_BODY_BYTE_CAP = 10 * 1024 * 1024  # 10MB


def _validate_url(url: str) -> None:
    if not url or not isinstance(url, str):
        raise ToolError("URL 不能为空")
    if len(url) > _MAX_URL_LEN:
        raise ToolError(f"URL 过长（>{_MAX_URL_LEN} 字符）")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ToolError(f"只支持 http/https，不支持 {parsed.scheme or '空'}")
    if parsed.username or parsed.password:
        raise ToolError("URL 不允许内嵌 user:pass 凭据")
    host = parsed.hostname or ""
    if "." not in host:
        raise ToolError(f"域名不合法（须含点号）：{host or '空'}")


async def _execute(tool_input: dict[str, Any]) -> str:
    url = tool_input["url"]
    _validate_url(url)
    method = (tool_input.get("method") or "GET").upper()
    if method not in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"):
        raise ToolError(f"不支持的方法：{method}")
    body = tool_input.get("body")
    if body is not None and not isinstance(body, dict):
        raise ToolError("body 必须是 JSON 对象")
    headers = tool_input.get("headers") or {}
    if not isinstance(headers, dict):
        raise ToolError("headers 必须是对象")

    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_S,
            transport=_TRANSPORT,
            follow_redirects=True,
            max_redirects=_MAX_REDIRECTS,
        ) as c:
            r = await c.request(
                method, url, json=body if body is not None else None, headers=headers
            )
    except httpx.TooManyRedirects:
        raise ToolError(f"重定向超过 {_MAX_REDIRECTS} 跳") from None
    except httpx.HTTPError as e:
        raise ToolError(f"请求失败：{type(e).__name__}") from e

    # 响应体上限 10MB 再读文本（lessons 3.7）
    if len(r.content) > _BODY_BYTE_CAP:
        text = r.content[:_BODY_BYTE_CAP].decode("utf-8", errors="replace")
        text += f"\n[响应体超过 {_BODY_BYTE_CAP // (1024 * 1024)}MB，已截断]"
    else:
        text = r.text

    parts: list[str] = [f"HTTP {r.status_code}"]
    # 跨域跳转不静默：完整跳转链写进结果（lessons 3.7 变通）
    if r.history:
        chain = " -> ".join(str(h.status_code) + " " + str(h.url) for h in r.history)
        parts.append(f"[重定向链] {chain} -> {r.status_code} {r.url}")
    if text:
        parts.append(text)
    return "\n".join(parts)


TOOL = Tool(
    name="http_request",
    description=(
        "发起一次不带凭据的 HTTP 请求，用于查询公开信息（API、网页、文档等）。"
        "返回状态码、（如有）重定向链、响应体文本。"
        "需要身份认证的请求不在此工具能力范围内。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "完整 URL，http/https"},
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"],
                "description": "HTTP 方法，默认 GET",
            },
            "body": {
                "type": "object",
                "description": "请求体（JSON 对象），仅 POST/PUT/PATCH 有意义",
            },
            "headers": {"type": "object", "description": "附加请求头（不要放任何凭据）"},
        },
        "required": ["url"],
    },
    execute=_execute,
    timeout_s=60,
    max_result_chars=100_000,
    concurrency_safe=True,  # 只读网络请求，M3 无并发但如实声明
)
