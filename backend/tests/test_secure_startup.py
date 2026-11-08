import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import CSRF_HEADER, CSRF_VALUE, create_app

_SECRET = "0123456789abcdef0123456789abcdef"  # 32 chars
_DATA_KEY = "fedcba9876543210fedcba9876543210"  # 32 chars


def _st(tmp_path, **kw):
    return Settings(
        data_dir=tmp_path,
        db_path=tmp_path / "t.db",
        secret=kw.pop("secret", _SECRET),
        initial_username="han",
        initial_password=kw.pop("initial_password", "strong-pass"),
        secure_cookies=kw.pop("secure_cookies", True),
        data_key=kw.pop("data_key", _DATA_KEY),
    )


def test_secure_mode_rejects_default_secret(tmp_path):
    with pytest.raises(RuntimeError):
        create_app(_st(tmp_path, secret="dev-secret-change-me"))


def test_secure_mode_rejects_example_secret(tmp_path):
    # .env.example 里的占位值同样过不了生产检查
    with pytest.raises(RuntimeError):
        create_app(_st(tmp_path, secret="please-change-me"))


def test_secure_mode_rejects_short_secret(tmp_path):
    with pytest.raises(RuntimeError):
        create_app(_st(tmp_path, secret="x" * 31))


def test_secure_mode_rejects_default_password(tmp_path):
    with pytest.raises(RuntimeError):
        create_app(_st(tmp_path, initial_password="dev-password"))


def test_secure_mode_rejects_empty_password(tmp_path):
    with pytest.raises(RuntimeError):
        create_app(_st(tmp_path, initial_password=""))


def test_secure_mode_accepts_strong_config(tmp_path):
    with TestClient(create_app(_st(tmp_path))) as c:
        assert c.get("/api/health").status_code == 200
        c.headers[CSRF_HEADER] = CSRF_VALUE
        r = c.post(
            "/api/auth/login", json={"username": "han", "password": "strong-pass"}
        )
        assert r.status_code == 200


def test_dev_mode_skips_strong_checks(tmp_path):
    # 本地 http 开发（secure_cookies=False）不受强校验约束
    with TestClient(create_app(_st(tmp_path, secure_cookies=False, secret="s"))) as c:
        assert c.get("/api/health").status_code == 200


# ---- M2：DATA_KEY（密钥加密主密钥，design §15.4）同样受生产强校验 ----


def test_secure_mode_rejects_missing_data_key(tmp_path):
    with pytest.raises(RuntimeError):
        create_app(_st(tmp_path, data_key=""))


def test_secure_mode_rejects_short_data_key(tmp_path):
    with pytest.raises(RuntimeError):
        create_app(_st(tmp_path, data_key="x" * 31))


def test_secure_mode_rejects_default_data_key(tmp_path):
    # from_env 在缺省时填充的 dev 兜底值，secure 模式必须拒绝
    with pytest.raises(RuntimeError):
        create_app(_st(tmp_path, data_key="please-change-me"))
