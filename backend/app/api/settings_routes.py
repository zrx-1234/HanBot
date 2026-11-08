"""GET/PUT /api/settings（design §12.6）：默认值 + 用户覆盖合并存储。"""

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.guard import require_login
from app.config import Settings
from app.db import models
from app.db.db import asession_scope

router = APIRouter(prefix="/api/settings", dependencies=[Depends(require_login)])

# design §4.3 的默认值；未覆盖的键 GET 时返回默认
DEFAULTS: dict[str, Any] = {
    "system_prompt": (
        "You are HanBot, the user's personal agent running on the user's own server. "
        "Be direct and useful. Respond in the user's language."
    ),
    "style": "",
    "max_concurrent_tasks": 2,
    "max_steps": 50,
    "task_timeout_minutes": 30,
    "bash_timeout_seconds": 120,
    "sandbox_memory_mb": 512,
    "storage_quota_gb": 10,
    "backup_retention": 14,
    "memory_token_budget": 1500,
    "review_time": "03:00",
}

_INT_RANGES: dict[str, tuple[int, int]] = {
    "max_concurrent_tasks": (1, 10),
    "max_steps": (1, 500),
    "task_timeout_minutes": (1, 720),
    "bash_timeout_seconds": (1, 3600),
    "sandbox_memory_mb": (128, 8192),
    "storage_quota_gb": (1, 1000),
    "backup_retention": (1, 365),
    "memory_token_budget": (0, 100000),
}

_STR_LENGTHS: dict[str, int] = {
    "system_prompt": 20000,
    "style": 2000,
}

_REVIEW_TIME_RE = re.compile(r"^(2[0-3]|[01]?\d):[0-5]\d$")


class SettingsBody(BaseModel):
    settings: dict[str, Any]


def _st(request: Request) -> Settings:
    return request.app.state.settings


def _validate(key: str, value: Any) -> None:
    if key in _INT_RANGES:
        lo, hi = _INT_RANGES[key]
        if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
            raise HTTPException(status_code=422, detail=f"{key} 必须是 {lo}~{hi} 的整数")
    elif key == "review_time":
        if not isinstance(value, str) or not _REVIEW_TIME_RE.match(value):
            raise HTTPException(status_code=422, detail="review_time 必须是 HH:MM 形式（24小时制）")
    elif key in _STR_LENGTHS:
        if not isinstance(value, str) or len(value) > _STR_LENGTHS[key]:
            raise HTTPException(
                status_code=422,
                detail=f"{key} 必须是不超过 {_STR_LENGTHS[key]} 字符的文本",
            )
    else:
        raise HTTPException(status_code=422, detail=f"未知设置项：{key}")


async def _load(st: Settings) -> dict[str, Any]:
    merged = dict(DEFAULTS)
    async with asession_scope(st) as s:
        rows = (await s.execute(select(models.SettingsRow))).scalars().all()
        for row in rows:
            if row.key in merged:
                merged[row.key] = json.loads(row.value)
    return merged


@router.get("")
async def get_settings(request: Request) -> dict[str, dict[str, Any]]:
    return {"settings": await _load(_st(request))}


@router.put("")
async def put_settings(body: SettingsBody, request: Request) -> dict[str, dict[str, Any]]:
    st = _st(request)
    for key, value in body.settings.items():
        _validate(key, value)

    merged = await _load(st)
    merged.update(body.settings)

    async with asession_scope(st) as s:
        for key, value in body.settings.items():
            row = (
                await s.execute(
                    select(models.SettingsRow).where(models.SettingsRow.key == key)
                )
            ).scalar_one_or_none()
            if row is not None:
                row.value = json.dumps(value)
            else:
                s.add(models.SettingsRow(key=key, value=json.dumps(value)))

    return {"settings": merged}
