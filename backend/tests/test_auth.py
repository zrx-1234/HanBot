import time

from fastapi.testclient import TestClient
from sqlalchemy import func, select

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
        # design §15.1 明确要求 argon2id，不是任意 argon2 变体
        assert row.password_hash.startswith("$argon2id$")


def test_session_without_cookie_is_anonymous(client):
    resp = client.get("/api/auth/session")
    assert resp.json() == {"logged_in": False, "username": None}


def test_corrupted_password_hash_is_401_not_500(client, settings: Settings):
    # .env.example 声称"改密码走数据库"——手工改坏哈希不该把登录变成永久500
    _login(client)
    with session_scope(settings) as s:
        row = s.execute(select(models.UserRow)).scalar_one()
        row.password_hash = "NOT-ARGON2"

    resp = _login(client)
    assert resp.status_code == 401


def test_oversized_credentials_rejected_422(client):
    resp = client.post(
        "/api/auth/login", json={"username": "a" * 100, "password": "b" * 3000}
    )
    assert resp.status_code == 422


def _lock_client(tmp_path, lockout_seconds: int = 900):
    from app.db import init_db

    st = Settings(
        data_dir=tmp_path,
        db_path=tmp_path / "t.db",
        secret="s",
        initial_username="han",
        initial_password="pw",
        secure_cookies=False,
        lockout_seconds=lockout_seconds,
    )
    init_db(st)  # 不经 lifespan，显式建表
    c = TestClient(create_app(st))
    c.headers[CSRF_HEADER] = CSRF_VALUE
    return c, st


def _post(c, password):  # type: ignore[no-untyped-def]
    return c.post("/api/auth/login", json={"username": "han", "password": password})


def test_locked_attempts_are_not_recorded(tmp_path):
    # 锁定期内的尝试不再续窗：锁到期时间由第5次失败固定，不会因继续尝试无限顺延
    c, st = _lock_client(tmp_path)
    for _ in range(5):
        assert _post(c, "bad").status_code == 401
    assert _post(c, "pw").status_code == 429
    assert _post(c, "bad").status_code == 429

    with session_scope(st) as s:
        fails = (
            s.execute(
                select(func.count())
                .select_from(models.LoginLogRow)
                .where(models.LoginLogRow.ok.is_(False))
            ).scalar_one()
        )
    assert fails == 5


def test_success_resets_failure_streak(tmp_path):
    # 成功登录打断"连续失败"：此后再错1次不该立刻触发旧账累计的锁定
    c, st = _lock_client(tmp_path)
    for _ in range(4):
        assert _post(c, "bad").status_code == 401
    assert _post(c, "pw").status_code == 200
    assert _post(c, "bad").status_code == 401
    # 旧语义下：窗口内已有5次失败，这次正确登录会被429
    assert _post(c, "pw").status_code == 200


def test_same_second_failures_after_success_count(tmp_path):
    # 活栈验收发现的真bug：成功与其后的失败落在同一秒时，秒级时间戳比较会漏计连续失败。
    # 连续性必须按记录顺序（id）判定，与时间戳精度无关。
    c, st = _lock_client(tmp_path)
    with session_scope(st) as s:
        # 同一事务里预置：1条成功 + 5条失败，created_at 全部同秒
        s.add(models.LoginLogRow(ip="testclient", ok=True))
        for _ in range(5):
            s.add(models.LoginLogRow(ip="testclient", ok=False))

    # 5次失败按记录顺序都发生在成功之后 → 应视为连续5次 → 锁定
    assert _post(c, "pw").status_code == 429


def test_lockout_after_repeated_failures(tmp_path):
    # 窗口必须显著大于 5 次 argon2 校验的总耗时（实测纯 CPU 约 2.3s，
    # 高负载下加 HTTP/DB 只会更多），否则第一次失败会滑出窗口导致漏锁。
    st = Settings(
        data_dir=tmp_path,
        db_path=tmp_path / "t.db",
        secret="s",
        initial_username="han",
        initial_password="pw",
        secure_cookies=False,
        lockout_seconds=30,
    )
    with TestClient(create_app(st)) as c:
        c.headers[CSRF_HEADER] = CSRF_VALUE
        for _ in range(5):
            r = c.post("/api/auth/login", json={"username": "han", "password": "bad"})
            assert r.status_code == 401

        # 第6次：密码正确也被锁
        r = c.post("/api/auth/login", json={"username": "han", "password": "pw"})
        assert r.status_code == 429

        # 窗口过后自动解锁：不真等30秒，直接把失败记录时间改到窗口外
        with session_scope(st) as s:
            from sqlalchemy import update

            s.execute(
                update(models.LoginLogRow)
                .where(models.LoginLogRow.ok.is_(False))
                .values(created_at=int(time.time()) - 31)
            )
        r = c.post("/api/auth/login", json={"username": "han", "password": "pw"})
        assert r.status_code == 200
