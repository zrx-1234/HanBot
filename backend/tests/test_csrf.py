from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _settings(tmp_path):
    return Settings(
        data_dir=tmp_path,
        db_path=tmp_path / "t.db",
        secret="s",
        initial_username="han",
        initial_password="pw",
        secure_cookies=False,
    )


def test_mutating_without_csrf_header_rejected(tmp_path):
    with TestClient(create_app(_settings(tmp_path))) as c:
        r = c.post("/api/auth/login", json={"username": "han", "password": "pw"})
        assert r.status_code == 403


def test_mutating_with_csrf_header_allowed(tmp_path):
    with TestClient(create_app(_settings(tmp_path))) as c:
        r = c.post(
            "/api/auth/login",
            json={"username": "han", "password": "pw"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert r.status_code == 200


def test_get_unaffected(tmp_path):
    with TestClient(create_app(_settings(tmp_path))) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/auth/session").status_code == 200
