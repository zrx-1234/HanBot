import time

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db import models, session_scope
from app.main import CSRF_HEADER, CSRF_VALUE, create_app


def _login(client, password="correct-password"):
    return client.post(
        "/api/auth/login", json={"username": "han", "password": password}
    )


def test_first_login_bootstraps_user_and_succeeds(client):
    # 空库首次登录：用环境初始凭据引导创建用户，并直接登录成功
    resp = _login(client)
    assert resp.status_code == 200

    resp = client.get("/api/auth/session")
    assert resp.status_code == 200
    assert resp.json() == {"logged_in": True, "username": "han"}


def test_wrong_password_rejected_and_logged(client, settings: Settings):
    # 先引导创建用户
    assert _login(client).status_code == 200
    client.post("/api/auth/logout")

    resp = _login(client, password="wrong-password")
    assert resp.status_code == 401

    resp = client.get("/api/auth/session")
    assert resp.json() == {"logged_in": False, "username": None}

    # 失败也留痕
    with session_scope(settings) as s:
        logs = s.execute(select(models.LoginLogRow)).scalars().all()
        assert any(row.ok is False for row in logs)


def test_logout_clears_session(client):
    assert _login(client).status_code == 200
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert client.get("/api/auth/session").json() == {"logged_in": False, "username": None}


def test_password_stored_as_argon2_hash(client, settings: Settings):
    _login(client)
    with session_scope(settings) as s:
        row = s.execute(select(models.UserRow)).scalar_one()
        assert row.password_hash != "correct-password"
        assert row.password_hash.startswith("$argon2")


def test_session_without_cookie_is_anonymous(client):
    resp = client.get("/api/auth/session")
    assert resp.json() == {"logged_in": False, "username": None}


def test_lockout_after_repeated_failures(tmp_path):
    st = Settings(
        data_dir=tmp_path,
        db_path=tmp_path / "t.db",
        secret="s",
        initial_username="han",
        initial_password="pw",
        secure_cookies=False,
        lockout_seconds=2,
    )
    with TestClient(create_app(st)) as c:
        c.headers[CSRF_HEADER] = CSRF_VALUE
        for _ in range(5):
            r = c.post("/api/auth/login", json={"username": "han", "password": "bad"})
            assert r.status_code == 401

        # 第6次：密码正确也被锁
        r = c.post("/api/auth/login", json={"username": "han", "password": "pw"})
        assert r.status_code == 429

        # 窗口过后自动解锁
        time.sleep(2.5)
        r = c.post("/api/auth/login", json={"username": "han", "password": "pw"})
        assert r.status_code == 200
