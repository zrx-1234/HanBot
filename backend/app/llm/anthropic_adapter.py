"""anthropic 格式适配器（design §8.1）。

职责：内部统一消息格式 ↔ anthropic API 格式互转、工具 schema 互转、
流式事件解析归一。不负责选源/重试/记账（那是 gateway 的事）。
"""

from collections.abc import AsyncIterator
from typing import Any

import anthropic.types as at

from app.llm.types import (
    Block,
    MessageDoneEvent,
    StreamEvent,
    TextBlock,
    TextDeltaEvent,
    ToolCallEvent,
    ToolResultBlock,
    ToolUseBlock,
    UMessage,
    Usage,
)


def _block_to_api(block: Block) -> dict[str, Any] | None:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text} if block.text else None
    if isinstance(block, ToolUseBlock):
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    if isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "content": block.content,
            "is_error": block.is_error,
        }
    return None


def to_api_messages(messages: list[UMessage]) -> list[dict[str, Any]]:
    """内部消息 → anthropic messages 参数。

    纯文本消息序列化成字符串 content（省 token）；混合 blocks 走数组。
    空 blocks 直接拒绝（anthropic 侧 400，宁可构造期炸）。
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        if not m.blocks:
            raise ValueError(f"消息（role={m.role}）blocks 为空，无法转换")
        api_blocks = [b for b in (_block_to_api(x) for x in m.blocks) if b is not None]
        if not api_blocks:
            raise ValueError(f"消息（role={m.role}）全部块为空内容，无法转换")
        if len(api_blocks) == 1 and api_blocks[0]["type"] == "text":
            out.append({"role": m.role, "content": api_blocks[0]["text"]})
        else:
            out.append({"role": m.role, "content": api_blocks})
    return out


def to_api_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """内部工具定义（name/description/input_schema）→ anthropic tools 参数。"""
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["input_schema"],
        }
        for t in tools
    ]


async def stream_anthropic(
    *,
    client: Any,
    model: str,
    system: str,
    messages: list[UMessage],
    tools: list[dict[str, Any]],
    max_tokens: int = 8192,
) -> AsyncIterator[StreamEvent]:
    """发起流式请求，产出归一化事件，最后一条恒为 MessageDoneEvent。

    thinking 块被丢弃：内部格式不保留签名块（lessons 2.4），
    文本与工具调用块正常透传。
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": to_api_messages(messages),
        "stream": True,
    }
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = to_api_tools(tools)

    usage = Usage()
    blocks: list[TextBlock | ToolUseBlock] = []
    # index → 正在拼装的块；tool 调用的 input 走 partial_json 增量拼装
    text_parts: dict[int, list[str]] = {}
    tool_buf: dict[int, dict[str, str]] = {}  # index -> {id, name, json}
    order: list[int] = []  # 块出现顺序
    stop_reason: str | None = None

    async for ev in await client.messages.create(**kwargs):
        if isinstance(ev, at.MessageStartEvent):
            u = ev.message.usage
            usage.input_tokens = u.input_tokens or 0
            usage.cache_creation_tokens = getattr(u, "cache_creation_input_tokens", 0) or 0
            usage.cached_tokens = getattr(u, "cache_read_input_tokens", 0) or 0
        elif isinstance(ev, at.ContentBlockStartEvent):
            cb = ev.content_block
            if isinstance(cb, at.TextBlock):
                text_parts[ev.index] = []
                order.append(ev.index)
            elif isinstance(cb, at.ToolUseBlock):
                tool_buf[ev.index] = {"id": cb.id, "name": cb.name, "json": ""}
                order.append(ev.index)
            # thinking / redacted_thinking 等其余块：丢弃（见 docstring）
        elif isinstance(ev, at.RawContentBlockDeltaEvent):
            d = ev.delta
            if isinstance(d, at.TextDelta) and ev.index in text_parts:
                text_parts[ev.index].append(d.text)
                yield TextDeltaEvent(text=d.text)
            elif isinstance(d, at.InputJSONDelta) and ev.index in tool_buf:
                tool_buf[ev.index]["json"] += d.partial_json
        elif isinstance(ev, at.MessageDeltaEvent):
            usage.output_tokens = ev.usage.output_tokens or 0
            # 方舟 Coding 端点在 start 事件不填 input_tokens，真实值在 delta.usage 里
            # （后到覆盖：官方 anthropic 的 delta.usage 不含 input，取到 0 不覆盖）
            delta_in = getattr(ev.usage, "input_tokens", 0) or 0
            if delta_in:
                usage.input_tokens = delta_in
            stop_reason = ev.delta.stop_reason
        elif isinstance(ev, at.MessageStopEvent):
            pass

    import json as _json

    for idx in order:
        if idx in text_parts:
            text = "".join(text_parts[idx])
            if text:
                blocks.append(TextBlock(text=text))
        elif idx in tool_buf:
            buf = tool_buf[idx]
            try:
                inp = _json.loads(buf["json"]) if buf["json"] else {}
            except _json.JSONDecodeError:
                inp = {"_raw": buf["json"]}
            blocks.append(ToolUseBlock(id=buf["id"], name=buf["name"], input=inp))
            yield ToolCallEvent(id=buf["id"], name=buf["name"], input=inp)

    final_blocks: list[TextBlock | ToolUseBlock | ToolResultBlock] = list(blocks)
    yield MessageDoneEvent(
        message=UMessage(role="assistant", blocks=final_blocks),
        stop_reason=stop_reason,
        usage=usage,
    )
