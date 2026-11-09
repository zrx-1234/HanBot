"""聊天闭环（design §5.1/§12.2/12.3）：sessions API + 消息落库 + 工具循环 + WS 流式。

网关打桩成剧本式响应，不打真网。M3 无任务态：纯问答不产生任务记录。
"""

import json
import time
from pathlib import Path

import pytest

from app.agent import runner as runner_module
from app.llm.types import (
    MessageDoneEvent,
    TextBlock,
    TextDeltaEvent,
    ToolCallEvent,
    ToolUseBlock,
    UMessage,
    Usage,
)


def _wait_for(client, path, predicate, timeout=10.0):
    """轮询 GET 直到条件满足（Runner 在后台事件循环里跑）。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = client.get(path).json()
        if predicate(last):
            return last
        time.sleep(0.05)
    raise AssertionError(
        f"等待超时：{path} 最后一次响应 {json.dumps(last, ensure_ascii=False)[:500]}"
    )


def _mk_done(text=None, tool=None, stop="end_turn") -> MessageDoneEvent:
    blocks = []
    if text:
        blocks.append(TextBlock(text=text))
    if tool:
        blocks.append(ToolUseBlock(id=tool["id"], name=tool["name"], input=tool["input"]))
    return MessageDoneEvent(
        message=UMessage(role="assistant", blocks=blocks),
        stop_reason=stop,
        usage=Usage(input_tokens=10, output_tokens=5),
    )


def _script(responses: list[list]) -> callable:  # type: ignore[type-arg]
    """把若干剧本（每剧本 = 一次 LLM 调用的事件列表）装成 gateway.chat。"""
    calls = {"n": 0}

    async def fake_chat(st, messages, **kw):  # type: ignore[no-untyped-def]
        idx = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        for ev in responses[idx]:
            yield ev

    return fake_chat, calls


def _create_session(client, title="测试会话") -> dict:
    r = client.post("/api/sessions", json={"title": title})
    assert r.status_code == 200
    return r.json()


class TestSessionsApi:
    def test_create_and_list(self, auth_client):
        body = _create_session(auth_client)
        assert body["uuid"]
        lst = auth_client.get("/api/sessions").json()["sessions"]
        assert [s["uuid"] for s in lst] == [body["uuid"]]

    def test_create_makes_session_dir(self, auth_client, settings):
        body = _create_session(auth_client)
        d = Path(settings.data_dir) / "sessions" / body["uuid"]
        assert d.is_dir()

    def test_requires_login(self, client):
        assert client.get("/api/sessions").status_code == 401
        assert client.post("/api/sessions", json={"title": "x"}).status_code == 401

    def test_messages_empty_initially(self, auth_client):
        body = _create_session(auth_client)
        r = auth_client.get(f"/api/sessions/{body['uuid']}/messages")
        assert r.status_code == 200
        assert r.json()["messages"] == []

    def test_chat_unknown_session_404(self, auth_client):
        r = auth_client.post(
            "/api/sessions/no-such-uuid/chat", json={"content": "hi"}
        )
        assert r.status_code == 404


class TestChatFlow:
    def test_plain_qa_saves_messages_in_order(self, auth_client, monkeypatch):
        """纯文本问答：用户消息先落库，assistant 回复后落库（lessons 2.1）。"""
        body = _create_session(auth_client)
        fake, calls = _script(
            [[TextDeltaEvent(text="你"), TextDeltaEvent(text="好"), _mk_done(text="你好")]]
        )
        monkeypatch.setattr(runner_module.gateway, "chat", fake)

        r = auth_client.post(
            f"/api/sessions/{body['uuid']}/chat", json={"content": "打个招呼"}
        )
        assert r.status_code == 200
        assert r.json()["user_message_id"] > 0

        msgs = _wait_for(
            auth_client,
            f"/api/sessions/{body['uuid']}/messages",
            lambda m: len(m["messages"]) >= 2,
        )["messages"]
        assert msgs[0]["role"] == "user"
        assert msgs[0]["blocks"][0]["text"] == "打个招呼"
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["blocks"][0]["text"] == "你好"

    def test_tool_round_full_sequence(self, auth_client, monkeypatch):
        """完整工具循环：问 → tool_use → tool_result → 最终回答。

        http_request 打桩；四条消息按序落库。
        """
        body = _create_session(auth_client)

        async def fake_run_tool(name, inp):  # type: ignore[no-untyped-def]
            return "HTTP 200\n{}"

        monkeypatch.setattr(runner_module, "run_tool", fake_run_tool)
        fake, calls = _script(
            [
                [
                    ToolCallEvent(
                        id="tu_1", name="http_request", input={"url": "https://api.example.com/x"}
                    ),
                    _mk_done(
                        text="我查一下",
                        tool={"id": "tu_1", "name": "http_request",
                              "input": {"url": "https://api.example.com/x"}},
                        stop="tool_use",
                    ),
                ],
                [_mk_done(text="查询结果：一切正常")],
            ]
        )
        monkeypatch.setattr(runner_module.gateway, "chat", fake)

        r = auth_client.post(
            f"/api/sessions/{body['uuid']}/chat", json={"content": "查一下 api 状态"}
        )
        assert r.status_code == 200

        msgs = _wait_for(
            auth_client,
            f"/api/sessions/{body['uuid']}/messages",
            lambda m: len(m["messages"]) >= 4,
        )["messages"]
        roles = [m["role"] for m in msgs]
        assert roles == ["user", "assistant", "user", "assistant"]
        # 第2条：assistant 带 text + tool_use
        assert msgs[1]["blocks"][0]["type"] == "text"
        assert msgs[1]["blocks"][1]["type"] == "tool_use"
        assert msgs[1]["blocks"][1]["name"] == "http_request"
        # 第3条：user 的 tool_result（design §8：tool_result 在 user 消息里）
        assert msgs[2]["blocks"][0]["type"] == "tool_result"
        assert msgs[2]["blocks"][0]["tool_use_id"] == "tu_1"
        assert "HTTP 200" in msgs[2]["blocks"][0]["content"]
        # 第4条：最终回答
        assert msgs[3]["blocks"][0]["text"] == "查询结果：一切正常"
        assert calls["n"] == 2  # 两次 LLM 调用

    def test_tool_error_goes_back_to_model(self, auth_client, monkeypatch):
        """工具失败不炸会话：错误文本作为 is_error tool_result 还给模型（design §5.8）。"""
        body = _create_session(auth_client)

        async def fake_run_tool(name, inp):  # type: ignore[no-untyped-def]
            from app.tools.registry import ToolError

            raise ToolError("URL 过长")

        monkeypatch.setattr(runner_module, "run_tool", fake_run_tool)
        fake, _ = _script(
            [
                [
                    _mk_done(
                        tool={"id": "tu_1", "name": "http_request", "input": {"url": "x" * 3000}},
                        stop="tool_use",
                    ),
                ],
                [_mk_done(text="URL 太长了，我换个方式")],
            ]
        )
        monkeypatch.setattr(runner_module.gateway, "chat", fake)

        assert (
            auth_client.post(
                f"/api/sessions/{body['uuid']}/chat", json={"content": "查"}
            ).status_code
            == 200
        )
        msgs = _wait_for(
            auth_client,
            f"/api/sessions/{body['uuid']}/messages",
            lambda m: len(m["messages"]) >= 4,
        )["messages"]
        tr = msgs[2]["blocks"][0]
        assert tr["type"] == "tool_result"
        assert tr["is_error"] is True
        assert "URL 过长" in tr["content"]

    def test_gateway_failure_reaches_user(self, auth_client, monkeypatch):
        """网关穷尽重试后：错误以 assistant 消息形态可见，会话不炸。"""
        from app.llm import gateway as gw

        body = _create_session(auth_client)

        async def failing_chat(st, messages, **kw):  # type: ignore[no-untyped-def]
            raise gw.LLMUnavailableError("连续 3 次失败：HTTP 500")
            yield  # pragma: no cover

        monkeypatch.setattr(runner_module.gateway, "chat", failing_chat)
        assert (
            auth_client.post(
                f"/api/sessions/{body['uuid']}/chat", json={"content": "hi"}
            ).status_code
            == 200
        )
        msgs = _wait_for(
            auth_client,
            f"/api/sessions/{body['uuid']}/messages",
            lambda m: len(m["messages"]) >= 2,
        )["messages"]
        assert msgs[1]["role"] == "assistant"
        assert "失败" in msgs[1]["blocks"][0]["text"]


class TestWebSocket:
    def test_ws_streams_deltas(self, auth_client, monkeypatch):
        body = _create_session(auth_client)
        fake, _ = _script(
            [
                [
                    TextDeltaEvent(text="你好"),
                    TextDeltaEvent(text="，世界"),
                    _mk_done(text="你好，世界"),
                ]
            ]
        )
        monkeypatch.setattr(runner_module.gateway, "chat", fake)

        with auth_client.websocket_connect(f"/ws?session={body['uuid']}") as ws:
            r = auth_client.post(
                f"/api/sessions/{body['uuid']}/chat", json={"content": "hi"}
            )
            assert r.status_code == 200

            got = []
            for _ in range(3):  # 两个 delta + 一个 done
                got.append(ws.receive_json())
        assert got[0]["type"] == "message_delta"
        assert got[0]["delta"] == "你好"
        assert got[1]["delta"] == "，世界"
        assert got[2]["type"] == "message_done"

    def test_ws_requires_login(self, client):
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws?session=x"):
                pass

    def test_ws_rejects_missing_session_param(self, auth_client):
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            with auth_client.websocket_connect("/ws"):
                pass
