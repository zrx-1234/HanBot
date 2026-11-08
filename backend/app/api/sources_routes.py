"""llm_sources CRUD + 连通性测试（design §4.4、§12.7）。

安全约束（design §15.4）：明文密钥只存在于请求与内存，落库走 AES-256-GCM，
响应只回显尾4位提示。
"""

import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.guard import require_login
from app.config import Settings
from app.crypto import decrypt_value, encrypt_value
from app.db import models
from app.db.db import asession_scope

router = APIRouter(prefix="/api/sources", dependencies=[Depends(require_login)])

# 测试注入点：单测 monkeypatch 成 httpx.MockTransport，不打真网
_TRANSPORT: httpx.AsyncBaseTransport | None = None


class ModelPrice(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    price_in: float = Field(ge=0)  # 每百万 token 美元
    price_out: float = Field(ge=0)


class SourceBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    format: str = Field(pattern="^(openai|anthropic)$")
    base_url: str = Field(min_length=1, max_length=256)
    api_key: str = Field(default="", max_length=512)
    models: list[ModelPrice] = Field(min_length=1)
    priority: int = Field(default=100, ge=0, le=10000)
    enabled: bool = True


class SourcePatch(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    models: list[ModelPrice] | None = None
    priority: int | None = None
    enabled: bool | None = None


def _st(request: Request) -> Settings:
    return request.app.state.settings


def _key_hint(plaintext: str) -> str:
    return "…" + plaintext[-4:]


def _row_to_dict(row: models.LlmSourceRow, st: Settings) -> dict[str, object]:
    try:
        hint = _key_hint(decrypt_value(st.data_key, row.api_key_encrypted))
    except ValueError:
        # DATA_KEY 轮换过 / 数据损坏：列表不能因此 500，给个明确提示
        hint = "…????"
    return {
        "id": row.id,
        "name": row.name,
        "format": row.format,
        "base_url": row.base_url,
        "models": json.loads(row.models),
        "priority": row.priority,
        "enabled": row.enabled,
        "status": row.status,
        "last_error": row.last_error,
        "api_key_hint": hint,
    }


async def _fetch(s: AsyncSession, source_id: int) -> models.LlmSourceRow:
    row = (
        await s.execute(
            select(models.LlmSourceRow).where(models.LlmSourceRow.id == source_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="源不存在")
    return row


@router.get("")
async def list_sources(request: Request) -> dict[str, list[dict[str, object]]]:
    st = _st(request)
    async with asession_scope(st) as s:
        rows = (
            await s.execute(
                select(models.LlmSourceRow).order_by(
                    models.LlmSourceRow.priority, models.LlmSourceRow.id
                )
            )
        ).scalars().all()
        return {"sources": [_row_to_dict(row, st) for row in rows]}


@router.post("")
async def create_source(body: SourceBody, request: Request) -> dict[str, object]:
    st = _st(request)
    if not body.api_key:
        raise HTTPException(status_code=422, detail="api_key 不能为空")
    async with asession_scope(st) as s:
        dup = (
            await s.execute(
                select(models.LlmSourceRow).where(models.LlmSourceRow.name == body.name)
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise HTTPException(status_code=409, detail="同名源已存在")
        row = models.LlmSourceRow(
            name=body.name,
            format=body.format,
            base_url=body.base_url.rstrip("/"),
            api_key_encrypted=encrypt_value(st.data_key, body.api_key),
            models=json.dumps([m.model_dump() for m in body.models]),
            priority=body.priority,
            enabled=body.enabled,
            status="ok",
        )
        s.add(row)
        await s.flush()
        return _row_to_dict(row, st)


@router.patch("/{source_id}")
async def patch_source(source_id: int, body: SourcePatch, request: Request) -> dict[str, object]:
    st = _st(request)
    async with asession_scope(st) as s:
        row = await _fetch(s, source_id)
        if body.name is not None:
            dup = (
                await s.execute(
                    select(models.LlmSourceRow)
                    .where(models.LlmSourceRow.name == body.name)
                    .where(models.LlmSourceRow.id != source_id)
                )
            ).scalar_one_or_none()
            if dup is not None:
                raise HTTPException(status_code=409, detail="同名源已存在")
            row.name = body.name
        if body.base_url is not None:
            row.base_url = body.base_url.rstrip("/")
        if body.api_key:
            row.api_key_encrypted = encrypt_value(st.data_key, body.api_key)
        if body.models is not None:
            row.models = json.dumps([m.model_dump() for m in body.models])
        if body.priority is not None:
            row.priority = body.priority
        if body.enabled is not None:
            row.enabled = body.enabled
        return _row_to_dict(row, st)


@router.delete("/{source_id}")
async def delete_source(source_id: int, request: Request) -> dict[str, int]:
    st = _st(request)
    async with asession_scope(st) as s:
        row = await _fetch(s, source_id)
        await s.delete(row)
        return {"deleted": source_id}


async def _probe(fmt: str, base_url: str, key: str) -> tuple[bool, str]:
    """连通性测试：openai 查 {base}/models，anthropic 查 {base}/v1/models。"""
    base = base_url.rstrip("/")
    if fmt == "anthropic":
        url = base + ("/models" if base.endswith("/v1") else "/v1/models")
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    else:
        url = base + "/models"
        headers = {"authorization": f"Bearer {key}"}
    try:
        async with httpx.AsyncClient(timeout=10.0, transport=_TRANSPORT) as c:
            r = await c.get(url, headers=headers)
    except httpx.HTTPError as e:
        return False, f"连接失败：{type(e).__name__}"
    if r.status_code == 200:
        try:
            data = r.json().get("data", [])
            n = len(data) if isinstance(data, list) else 0
        except ValueError:
            n = 0
        return True, f"连通正常，{n} 个模型"
    return False, f"HTTP {r.status_code}"


@router.post("/{source_id}/test")
async def test_source(source_id: int, request: Request) -> dict[str, object]:
    st = _st(request)
    async with asession_scope(st) as s:
        row = await _fetch(s, source_id)
        try:
            key = decrypt_value(st.data_key, row.api_key_encrypted)
        except ValueError:
            raise HTTPException(
                status_code=500, detail="密钥解密失败：HANBOT_DATA_KEY 与加密时不一致"
            ) from None
        ok, detail = await _probe(row.format, row.base_url, key)
        if ok:
            row.status = "ok"
            row.last_error = None
            row.cooldown_until = None
        else:
            # degraded 语义归 M3 网关运行时管理；此处只留最近一次测试结果
            row.last_error = detail[:500]
        return {"ok": ok, "detail": detail}
