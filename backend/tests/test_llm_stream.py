"""anthropic 流式事件解析归一（design §8.1：适配器负责流式事件解析归一）。

用真实 anthropic SDK 的事件类型构造假流，不打真网。
"""

import anthropic.types as at
import pytest
from anthropic.types.raw_message_delta_event import Delta

from app.llm.anthropic_adapter import stream_anthropic
from app.llm.types import TextDeltaEvent, ToolCallEvent


def _mk_events() -> list:
    """一段典型的 anthropic SSE 事件流：文本 + 一个工具调用 + usage。"""
    return [
        at.MessageStartEvent(
            type="message_start",
            message=at.Message(
                id="msg_1",
                type="message",
                role="assistant",
                model="glm-latest",
                content=[],
                stop_reason=None,
                stop_sequence=None,
                usage=at.Usage(
                    input_tokens=100, output_tokens=1,
                    cache_creation_input_tokens=0, cache_read_input_tokens=0,
                ),
            ),
        ),
        at.ContentBlockStartEvent(
            type="content_block_start", index=0,
            content_block=at.TextBlock(type="text", text=""),
        ),
        at.RawContentBlockDeltaEvent(
            type="content_block_delta", index=0,
            delta=at.TextDelta(type="text_delta", text="你好"),
        ),
        at.ContentBlockStopEvent(type="content_block_stop", index=0),
        at.ContentBlockStartEvent(
            type="content_block_start",
            index=1,
            content_block=at.ToolUseBlock(
                type="tool_use", id="tu_1", name="http_request", input={}
            ),
        ),
        at.RawContentBlockDeltaEvent(
            type="content_block_delta", index=1,
            delta=at.InputJSONDelta(type="input_json_delta", partial_json='{"url": "https://x'),
        ),
        at.RawContentBlockDeltaEvent(
            type="content_block_delta", index=1,
            delta=at.InputJSONDelta(type="input_json_delta", partial_json='.example.com"}'),
        ),
        at.ContentBlockStopEvent(type="content_block_stop", index=1),
        at.MessageDeltaEvent(
            type="message_delta",
            delta=Delta(stop_reason="tool_use", stop_sequence=None),
            usage=at.MessageDeltaUsage(output_tokens=42),
        ),
        at.MessageStopEvent(type="message_stop"),
    ]


class _FakeMessages:
    def __init__(self, events):
        self._events = events
        self.calls: list[dict] = []

    async def create(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        events = self._events

        async def _gen():
            for e in events:
                yield e

        return _gen()


class _FakeClient:
    def __init__(self, events):
        self.messages = _FakeMessages(events)


@pytest.mark.anyio
async def test_stream_yields_deltas_and_final():
    events = []
    async for ev in stream_anthropic(
        client=_FakeClient(_mk_events()), model="glm-latest", system="s", messages=[], tools=[]
    ):
        events.append(ev)

    deltas = [e for e in events if isinstance(e, TextDeltaEvent)]
    calls = [e for e in events if isinstance(e, ToolCallEvent)]
    assert [d.text for d in deltas] == ["你好"]

    # 工具调用事件：input 的 partial_json 拼装成完整 JSON
    assert len(calls) == 1
    assert calls[0].name == "http_request"
    assert calls[0].input == {"url": "https://x.example.com"}

    # 最终消息：blocks 齐全 + stop_reason + usage
    final = events[-1]
    assert final.message.role == "assistant"
    assert final.message.blocks[0].text == "你好"
    assert final.message.blocks[1].id == "tu_1"
    assert final.stop_reason == "tool_use"
    assert final.usage.input_tokens == 100
    assert final.usage.output_tokens == 42


@pytest.mark.anyio
async def test_stream_pure_text_no_tool():
    events = [
        at.MessageStartEvent(
            type="message_start",
            message=at.Message(
                id="msg_2", type="message", role="assistant", model="m", content=[],
                stop_reason=None, stop_sequence=None,
                usage=at.Usage(input_tokens=10, output_tokens=1,
                               cache_creation_input_tokens=0, cache_read_input_tokens=0),
            ),
        ),
        at.ContentBlockStartEvent(
            type="content_block_start", index=0,
            content_block=at.TextBlock(type="text", text=""),
        ),
        at.RawContentBlockDeltaEvent(
            type="content_block_delta", index=0,
            delta=at.TextDelta(type="text_delta", text="回答完毕"),
        ),
        at.ContentBlockStopEvent(type="content_block_stop", index=0),
        at.MessageDeltaEvent(
            type="message_delta",
            delta=Delta(stop_reason="end_turn", stop_sequence=None),
            usage=at.MessageDeltaUsage(output_tokens=5),
        ),
        at.MessageStopEvent(type="message_stop"),
    ]
    out = []
    async for ev in stream_anthropic(
        client=_FakeClient(events), model="m", system="s", messages=[], tools=[]
    ):
        out.append(ev)

    final = out[-1]
    assert final.stop_reason == "end_turn"
    assert len(final.message.blocks) == 1
    assert final.message.blocks[0].text == "回答完毕"
    assert final.usage.output_tokens == 5


@pytest.mark.anyio
async def test_stream_usage_from_delta():
    """方舟实际行为：message_start.usage.input_tokens=0，真实值在 message_delta.usage 里。

    （M3 活栈验收发现：方舟 Coding 端点不在 start 事件填充 input_tokens）
    """
    events = [
        at.MessageStartEvent(
            type="message_start",
            message=at.Message(
                id="msg_3", type="message", role="assistant", model="m", content=[],
                stop_reason=None, stop_sequence=None,
                usage=at.Usage(input_tokens=0, output_tokens=0,
                               cache_creation_input_tokens=0, cache_read_input_tokens=0),
            ),
        ),
        at.ContentBlockStartEvent(
            type="content_block_start", index=0,
            content_block=at.TextBlock(type="text", text=""),
        ),
        at.RawContentBlockDeltaEvent(
            type="content_block_delta", index=0,
            delta=at.TextDelta(type="text_delta", text="ok"),
        ),
        at.ContentBlockStopEvent(type="content_block_stop", index=0),
        at.MessageDeltaEvent(
            type="message_delta",
            delta=Delta(stop_reason="end_turn", stop_sequence=None),
            usage=at.MessageDeltaUsage(input_tokens=13, output_tokens=7),
        ),
        at.MessageStopEvent(type="message_stop"),
    ]
    out = []
    async for ev in stream_anthropic(
        client=_FakeClient(events), model="m", system="s", messages=[], tools=[]
    ):
        out.append(ev)

    final = out[-1]
    assert final.usage.input_tokens == 13
    assert final.usage.output_tokens == 7
