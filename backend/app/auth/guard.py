"""登录态守卫：业务路由统一挂它（design §12：cookie 会话认证）。"""

from fastapi import HTTPException, Request

from app.auth.session import COOKIE_NAME, read_session_token


def require_login(request: Request) -> None:
    settings = request.app.state.settings
    token = request.cookies.get(COOKIE_NAME)
    if not token or read_session_token(settings.secret, token) is None:
        raise HTTPException(status_code=401, detail="未登录")
