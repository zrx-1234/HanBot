"""会话与聊天路由（design §12.2/12.3）。

M3 范围：会话创建/列表、消息列表、发消息（触发 Runner）。
会话删除（含目录+二次确认）是 M6 的事。
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.runner import new_session_uuid, run_chat
from app.auth.guard import require_login
from app.config import Settings
from app.db import models
from app.db.db import asession_scope

router = APIRouter(prefix="/api/sessions", dependencies=[Depends(require_login)])


class SessionBody(BaseModel):
    title: str = Field(default="", max_length=256)


class ChatBody(BaseModel):
    content: str = Field(min_length=1, max_length=50_000)


def _st(request: Request) -> Settings:
    return request.app.state.settings


@router.get("")
async def list_sessions(request: Request) -> dict[str, list[dict[str, object]]]:
    st = _st(request)
    async with asession_scope(st) as s:
        rows = (
            await s.execute(
                select(models.SessionRow).order_by(models.SessionRow.updated_at.desc())
            )
        ).scalars().all()
        return {
            "sessions": [
                {"uuid": r.uuid, "title": r.title, "updated_at": r.updated_at}
                for r in rows
            ]
        }


@router.post("")
async def create_session(body: SessionBody, request: Request) -> dict[str, object]:
    st = _st(request)
    session_uuid = new_session_uuid()
    dir_path = st.data_dir / "sessions" / session_uuid
    dir_path.mkdir(parents=True, exist_ok=True)
    async with asession_scope(st) as s:
        row = models.SessionRow(
            uuid=session_uuid,
            title=body.title,
            dir_path=str(dir_path),
        )
        s.add(row)
    return {"uuid": session_uuid, "title": body.title}


async def _get_session_row(st: Settings, session_uuid: str) -> models.SessionRow:
    async with asession_scope(st) as s:
        row = (
            await s.execute(
                select(models.SessionRow).where(models.SessionRow.uuid == session_uuid)
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        return row


@router.get("/{session_uuid}/messages")
async def list_messages(session_uuid: str, request: Request) -> dict[str, object]:
    st = _st(request)
    await _get_session_row(st, session_uuid)
    async with asession_scope(st) as s:
        rows = (
            await s.execute(
                select(models.MessageRow)
                .where(models.MessageRow.session_uuid == session_uuid)
                .order_by(models.MessageRow.id)
            )
        ).scalars().all()
        import json as _json

        return {
            "messages": [
                {
                    "id": r.id,
                    "role": r.role,
                    "blocks": _json.loads(r.content),
                    "created_at": r.created_at,
                }
                for r in rows
            ]
        }


@router.post("/{session_uuid}/chat")
async def chat(session_uuid: str, body: ChatBody, request: Request) -> dict[str, object]:
    """发消息：用户消息先落库，Runner 后台执行（lessons 2.1）。"""
    st = _st(request)
    await _get_session_row(st, session_uuid)

    from app.agent.runner import _save_message
    from app.llm.types import TextBlock, UMessage

    user_mid = await _save_message(
        st, session_uuid, UMessage(role="user", blocks=[TextBlock(text=body.content)])
    )

    asyncio.get_running_loop().create_task(run_chat(st, session_uuid))
    return {"user_message_id": user_mid}
