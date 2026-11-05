import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture()
def settings(tmp_path):
    return Settings(
        data_dir=tmp_path,
        db_path=tmp_path / "test.db",
        secret="test-secret",
        initial_username="han",
        initial_password="correct-password",
        secure_cookies=False,
    )


@pytest.fixture()
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c
