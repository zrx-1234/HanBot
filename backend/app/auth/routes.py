from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.passwords import hash_password, verify_password
from app.auth.session import (
    COOKIE_NAME,
    MAX_AGE_SECONDS,
    issue_session_token,
    read_session_token,
)
from app.config import Settings
from app.db import models, session_scope

router = APIRouter(prefix="/api/auth")


class LoginBody(BaseModel):
    username: str
    password: str


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _ensure_bootstrapped_user(st: Settings) -> None:
    """users 空库时，用环境里的初始凭据创建唯一的用户。"""
    with session_scope(st) as s:
        row = (
            s.execute(
                select(models.UserRow).where(models.UserRow.username == st.initial_username)
            ).scalar_one_or_none()
        )
        if row is None:
            s.add(
                models.UserRow(
                    username=st.initial_username,
                    password_hash=hash_password(st.initial_password),
                )
            )


def _record_login(st: Settings, ip: str, ok: bool) -> None:
    with session_scope(st) as s:
        s.add(models.LoginLogRow(ip=ip, ok=ok))


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response) -> dict[str, str | bool]:
    st = _settings(request)
    _ensure_bootstrapped_user(st)

    with session_scope(st) as s:
        row = (
            s.execute(
                select(models.UserRow).where(models.UserRow.username == body.username)
            ).scalar_one_or_none()
        )
        ok = row is not None and verify_password(row.password_hash, body.password)

    _record_login(st, _client_ip(request), ok)
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
