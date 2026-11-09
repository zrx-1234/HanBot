"""Agent 执行引擎——单步循环（design §5，lessons 2.1）。

while 状态机：CALL_LLM →（有 tool_use → EXEC_TOOLS → CALL_LLM）|（纯文本 → DONE）。
每步先写库再广播；用户消息由 API 层先落库（lessons 2.1）。
M3 无任务态/强停/确认（M4/M5 的事），max_steps 上限已生效。
"""

import json
import logging
import uuid as uuid_mod
from typing import Any, Literal

from sqlalchemy import select

from app.config import Settings
from app.db import models
from app.db.db import asession_scope
from app.llm import gateway
from app.llm.types import (
    Block,
    MessageDoneEvent,
    TextBlock,
    TextDeltaEvent,
    ToolResultBlock,
    ToolUseBlock,
    UMessage,
)
from app.tools import get_tool_definitions, run_tool
from app.tools.registry import ToolError
from app.ws import manager

logger = logging.getLogger("hanbot.agent")

_MAX_CONTEXT_MESSAGES = 50  # M3 简单窗口；压缩摘要是 P2 的事


def blocks_to_json(blocks: list[Block]) -> str:
    out: list[dict[str, Any]] = []
    for b in blocks:
        if isinstance(b, TextBlock):
            out.append({"type": "text", "text": b.text})
        elif isinstance(b, ToolUseBlock):
            out.append(
                {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
            )
        elif isinstance(b, ToolResultBlock):
            out.append(
                {
                    "type": "tool_result",
                    "tool_use_id": b.tool_use_id,
                    "content": b.content,
                    "is_error": b.is_error,
                }
            )
    return json.dumps(out, ensure_ascii=False)


def blocks_from_json(raw: str, role: Literal["user", "assistant"]) -> UMessage:
    blocks: list[Block] = []
    for b in json.loads(raw):
        if b["type"] == "text":
            blocks.append(TextBlock(text=b["text"]))
        elif b["type"] == "tool_use":
            blocks.append(ToolUseBlock(id=b["id"], name=b["name"], input=b["input"]))
        elif b["type"] == "tool_result":
            blocks.append(
                ToolResultBlock(
                    tool_use_id=b["tool_use_id"],
                    content=b["content"],
                    is_error=b.get("is_error", False),
                )
            )
    return UMessage(role=role, blocks=blocks)


async def _load_context(st: Settings, session_uuid: str) -> list[UMessage]:
    async with asession_scope(st) as s:
        rows = (
            await s.execute(
                select(models.MessageRow)
                .where(models.MessageRow.session_uuid == session_uuid)
                .order_by(models.MessageRow.id.desc())
                .limit(_MAX_CONTEXT_MESSAGES)
            )
        ).scalars().all()
    # 倒序取最近 N 条再翻回正序
    msgs = [blocks_from_json(r.content, r.role) for r in reversed(rows)]  # type: ignore[arg-type]
    return msgs


async def _load_system_prompt(st: Settings) -> str:
    from app.api.settings_routes import _load

    values = await _load(st)
    parts = [values["system_prompt"]]
    if values.get("style"):
        parts.append(f"回答风格：{values['style']}")
    return "\n\n".join(parts)


async def _save_message(st: Settings, session_uuid: str, msg: UMessage) -> int:
    async with asession_scope(st) as s:
        row = models.MessageRow(
            session_uuid=session_uuid,
            role=msg.role,
            content=blocks_to_json(msg.blocks),
        )
        s.add(row)
        await s.flush()
        mid = row.id
    return mid


async def _broadcast(session_uuid: str, event: dict[str, Any]) -> None:
    await manager.broadcast(session_uuid, event)


async def run_chat(st: Settings, session_uuid: str) -> None:
    """对某会话执行一轮 Agent 循环（用户消息已入库）。"""
    try:
        await _run_chat_inner(st, session_uuid)
    except gateway.LLMError as e:
        logger.warning("LLM 调用失败 session=%s: %s", session_uuid, e)
        await _save_message(
            st,
            session_uuid,
            UMessage(role="assistant", blocks=[TextBlock(text=f"LLM 调用失败：{e}")]),
        )
        await _broadcast(
            session_uuid, {"type": "error", "session_uuid": session_uuid, "detail": str(e)}
        )
    except Exception:  # noqa: BLE001 —— Runner 永不让异常漏出到 asyncio 默认处理器
        logger.exception("Runner 异常 session=%s", session_uuid)
        await _save_message(
            st,
            session_uuid,
            UMessage(role="assistant", blocks=[TextBlock(text="内部错误，请重试。")]),
        )
        await _broadcast(
            session_uuid, {"type": "error", "session_uuid": session_uuid, "detail": "内部错误"}
        )


async def _run_chat_inner(st: Settings, session_uuid: str) -> None:
    from app.api.settings_routes import _load

    settings_values = await _load(st)
    max_steps = settings_values["max_steps"]

    tools = get_tool_definitions()
    assistant_mid: int | None = None

    for _step in range(max_steps):
        context = await _load_context(st, session_uuid)
        system = await _load_system_prompt(st)

        done_ev: MessageDoneEvent | None = None
        text_acc = ""
        async for ev in gateway.chat(st, context, system=system, tools=tools):
            if isinstance(ev, TextDeltaEvent):
                text_acc += ev.text
                await _broadcast(
                    session_uuid,
                    {"type": "message_delta", "session_uuid": session_uuid, "delta": ev.text},
                )
            elif isinstance(ev, MessageDoneEvent):
                done_ev = ev

        if done_ev is None:
            raise RuntimeError("网关未产出 MessageDoneEvent")

        # 先写库再广播/执行工具（design §5.4）
        assistant_mid = await _save_message(st, session_uuid, done_ev.message)

        tool_uses = [b for b in done_ev.message.blocks if isinstance(b, ToolUseBlock)]
        if not tool_uses:
            await _broadcast(
                session_uuid,
                {"type": "message_done", "session_uuid": session_uuid, "message_id": assistant_mid},
            )
            return

        # EXEC_TOOLS：串行执行（Phase 1 全串行，lessons 3.3）
        results: list[ToolResultBlock] = []
        for tu in tool_uses:
            try:
                content = await run_tool(tu.name, tu.input)
                results.append(ToolResultBlock(tool_use_id=tu.id, content=content))
            except ToolError as e:
                results.append(
                    ToolResultBlock(tool_use_id=tu.id, content=str(e), is_error=True)
                )
        await _save_message(
            st, session_uuid, UMessage(role="user", blocks=list(results))
        )
        # 回到 CALL_LLM

    # 超过 max_steps：以失败消息收尾（M3 无任务态；M4 起此处置 failed 并通知）
    await _save_message(
        st,
        session_uuid,
        UMessage(
            role="assistant",
            blocks=[TextBlock(text=f"已达到单次执行步数上限（{max_steps}），本次执行停止。")],
        ),
    )
    await _broadcast(
        session_uuid,
        {
            "type": "message_done",
            "session_uuid": session_uuid,
            "message_id": assistant_mid or 0,
        },
    )


def new_session_uuid() -> str:
    return str(uuid_mod.uuid4())
