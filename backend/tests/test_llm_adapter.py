"""内部统一消息格式 ↔ anthropic API 格式互转（design §8.1：消息历史内部统一格式，
换适配器即可，不存在格式漂移）。"""

from app.llm.anthropic_adapter import to_api_messages, to_api_tools
from app.llm.types import (
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UMessage,
)


class TestToApiMessages:
    def test_plain_text_messages(self):
        msgs = [
            UMessage(role="user", blocks=[TextBlock(text="你好")]),
            UMessage(role="assistant", blocks=[TextBlock(text="在的")]),
        ]
        api = to_api_messages(msgs)
        # 单纯文本消息序列化成字符串内容（更省 token）
        assert api == [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "在的"},
        ]

    def test_tool_use_round(self):
        """完整一轮工具调用：assistant 发 tool_use，user 回 tool_result。"""
        msgs = [
            UMessage(role="user", blocks=[TextBlock(text="查北京天气")]),
            UMessage(
                role="assistant",
                blocks=[
                    TextBlock(text="我查一下"),
                    ToolUseBlock(id="tu_1", name="http_request", input={"url": "https://w.example/api"}),
                ],
            ),
            UMessage(
                role="user",
                blocks=[ToolResultBlock(tool_use_id="tu_1", content='{"temp": 5}', is_error=False)],
            ),
        ]
        api = to_api_messages(msgs)
        assert api[0] == {"role": "user", "content": "查北京天气"}
        assert api[1]["role"] == "assistant"
        assert {"type": "text", "text": "我查一下"} in api[1]["content"]
        assert {
            "type": "tool_use",
            "id": "tu_1",
            "name": "http_request",
            "input": {"url": "https://w.example/api"},
        } in api[1]["content"]
        assert api[2]["role"] == "user"
        assert {
            "type": "tool_result",
            "tool_use_id": "tu_1",
            "content": '{"temp": 5}',
            "is_error": False,
        } in api[2]["content"]

    def test_tool_result_error_flag(self):
        msgs = [
            UMessage(
                role="user",
                blocks=[ToolResultBlock(tool_use_id="tu_9", content="boom", is_error=True)],
            ),
        ]
        api = to_api_messages(msgs)
        assert api[0]["content"][0]["is_error"] is True

    def test_empty_blocks_rejected(self):
        # 空 blocks 的消息序列化会产生空 content，anthropic 会 400——构造期就拦
        import pytest

        with pytest.raises(ValueError):
            to_api_messages([UMessage(role="user", blocks=[])])


class TestToApiTools:
    def test_tool_schema_conversion(self):
        tools = [
            {
                "name": "http_request",
                "description": "发起 HTTP 请求",
                "input_schema": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            }
        ]
        api = to_api_tools(tools)
        assert api == [
            {
                "name": "http_request",
                "description": "发起 HTTP 请求",
                "input_schema": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            }
        ]
