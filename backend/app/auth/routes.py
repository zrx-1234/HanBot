import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.auth.passwords import hash_password, verify_password
from app.auth.session import (
    COOKIE_NAME,
    MAX_AGE_SECONDS,
    issue_session_token,
    read_session_token,
)
from app.config import Settings
from app.db import models
from app.db.db import asession_scope

router = APIRouter(prefix="/api/auth")


class LoginBody(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _ensure_bootstrapped_user(st: Settings) -> None:
    """users 空库时，用环境里的初始凭据创建唯一的用户。"""
    async with asession_scope(st) as s:
        row = (
            await s.execute(
                select(models.UserRow).where(models.UserRow.username == st.initial_username)
            )
        ).scalar_one_or_none()
        if row is None:
            s.add(
                models.UserRow(
                    username=st.initial_username,
                    password_hash=hash_password(st.initial_password),
                )
            )


async def _record_login(st: Settings, ip: str, ok: bool) -> None:
    async with asession_scope(st) as s:
        s.add(models.LoginLogRow(ip=ip, ok=ok))


async def _recent_fail_count(st: Settings, ip: str) -> int:
    """窗口内"最近一次成功登录之后"的连续失败数。

    连续性按记录顺序（id）判定而非秒级时间戳：成功与其后失败同秒落库时，
    时间戳比较会漏计（活栈验收实测发现）。窗口边界仍用时间戳。
    """
    cutoff = int(time.time()) - st.lockout_seconds
    async with asession_scope(st) as s:
        last_ok_id = (
            await s.execute(
                select(func.max(models.LoginLogRow.id)).where(
                    models.LoginLogRow.ip == ip,
                    models.LoginLogRow.ok.is_(True),
                    models.LoginLogRow.created_at > cutoff,
                )
            )
        ).scalar()
        return (
            await s.execute(
                select(func.count())
                .select_from(models.LoginLogRow)
                .where(
                    models.LoginLogRow.ip == ip,
                    models.LoginLogRow.ok.is_(False),
                    models.LoginLogRow.created_at > cutoff,
                    models.LoginLogRow.id > func.coalesce(last_ok_id, 0),
                )
            )
        ).scalar_one()


async def _is_locked(st: Settings, ip: str) -> bool:
    return await _recent_fail_count(st, ip) >= st.lockout_threshold


@router.post("/login")
async def login(
    body: LoginBody, request: Request, response: Response
) -> dict[str, str | bool]:
    st = _settings(request)
    ip = _client_ip(request)

    if await _is_locked(st, ip):
        # 锁定期固定：到期时间由第N次失败决定，被锁期间的尝试不计不续
        raise HTTPException(status_code=429, detail="登录失败次数过多，稍后再试")

    await _ensure_bootstrapped_user(st)

    async with asession_scope(st) as s:
        row = (
            await s.execute(
                select(models.UserRow).where(models.UserRow.username == body.username)
            )
        ).scalar_one_or_none()
        ok = row is not None and verify_password(row.password_hash, body.password)

    await _record_login(st, ip, ok)
    if not ok:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = issue_session_token(st.secret, body.username)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=MAX_AGE_SECONDS,
        httponly=True,
        samesite="strict",
        secure=st.secure_cookies,
    )
    return {"logged_in": True, "username": body.username}


@router.post("/logout")
def logout(response: Response) -> dict[str, str | bool | None]:
    response.delete_cookie(COOKIE_NAME)
    return {"logged_in": False, "username": None}


@router.get("/session")
def whoami(request: Request) -> dict[str, str | bool | None]:
    st = _settings(request)
    token = request.cookies.get(COOKIE_NAME)
    username = read_session_token(st.secret, token) if token else None
    return {"logged_in": username is not None, "username": username}
