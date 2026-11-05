"""安全回归锁：评审发现 design.md §15 的关键属性没有任何测试钉住（I6）。

这些测试钉的是已存在的行为——它们立即通过是对的：目的是任何未来的改动
悄悄削弱这些属性时套件变红。新增行为仍走 RED→GREEN。
"""

from fastapi.testclient import TestClient

from app.auth.session import COOKIE_NAME, issue_session_token
from app.config import Settings
from app.main import CSRF_HEADER, CSRF_VALUE, create_app

_SECRET = "0123456789abcdef0123456789abcdef"


def _st(tmp_path, **kw):
    return Settings(
        data_dir=tmp_path,
        db_path=tmp_path / "t.db",
        secret=kw.pop("secret", _SECRET),
        initial_username="han",
        initial_password="pw",
        secure_cookies=kw.pop("secure_cookies", True),
    )


def test_cookie_flags_in_secure_mode(tmp_path):
    # design §15.2：HttpOnly + SameSite=Strict + Secure，三者缺一即红
    with TestClient(create_app(_st(tmp_path))) as c:
        c.headers[CSRF_HEADER] = CSRF_VALUE
        r = c.post("/api/auth/login", json={"username": "han", "password": "pw"})
        assert r.status_code == 200
        set_cookie = r.headers["set-cookie"].lower()
        assert "httponly" in set_cookie
        assert "samesite=strict" in set_cookie
        assert "secure" in set_cookie
        assert COOKIE_NAME in set_cookie


def test_garbage_token_is_anonymous(tmp_path):
    with TestClient(create_app(_st(tmp_path))) as c:
        c.cookies.set(COOKIE_NAME, "not-a-token")
        r = c.get("/api/auth/session")
        assert r.json() == {"logged_in": False, "username": None}


def test_wrong_secret_token_is_anonymous(tmp_path):
    # 用别的密钥签出的合法 token 也必须被拒
    forged = issue_session_token("attacker-knows-format", "han")
    with TestClient(create_app(_st(tmp_path))) as c:
        c.cookies.set(COOKIE_NAME, forged)
        r = c.get("/api/auth/session")
        assert r.json() == {"logged_in": False, "username": None}
