"""sources CRUD + 连通性测试按钮。

关键安全断言：明文密钥只进请求，永不回显、永不落库明文（design §15.4）。
连通性测试用 httpx.MockTransport 注入，不打真网。
"""

import json
import sqlite3

import httpx

import app.api.sources_routes as sources_module


def _create(client, **over):
    body = {
        "name": "主源",
        "format": "openai",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-abcdef123456",
        "models": [{"name": "gpt-test", "price_in": 1.0, "price_out": 2.0}],
    }
    body.update(over)
    return client.post("/api/sources", json=body)


def _raw_row(settings, source_id):
    con = sqlite3.connect(settings.db_path)
    try:
        return con.execute(
            "SELECT name, api_key_encrypted, format, base_url FROM llm_sources"
            " WHERE id = ?",
            (source_id,),
        ).fetchone()
    finally:
        con.close()


def test_create_source_masks_key_everywhere(auth_client, settings):
    resp = _create(auth_client)
    assert resp.status_code == 200
    body = resp.json()

    # 响应里不出现完整密钥，只给尾4位提示
    assert "sk-abcdef123456" not in json.dumps(body, ensure_ascii=False)
    assert body["api_key_hint"].endswith("3456")
    assert body["status"] == "ok"

    # 落库是密文
    _, enc, _, _ = _raw_row(settings, body["id"])
    assert enc and "sk-abcdef123456" not in enc


def test_sources_require_login(client):
    assert client.get("/api/sources").status_code == 401
    resp = _create(client)
    assert resp.status_code == 401


def test_create_rejects_duplicate_name(auth_client):
    assert _create(auth_client).status_code == 200
    resp = _create(auth_client, name="主源")
    assert resp.status_code == 409


def test_create_validates_fields(auth_client):
    assert _create(auth_client, format="google").status_code == 422
    assert _create(auth_client, models=[]).status_code == 422
    assert _create(auth_client, api_key="").status_code == 422
    assert _create(
        auth_client, models=[{"name": "m", "price_in": -1, "price_out": 0}]
    ).status_code == 422


def test_list_and_patch(auth_client):
    body = _create(auth_client).json()
    lst = auth_client.get("/api/sources").json()["sources"]
    assert len(lst) == 1
    assert lst[0]["id"] == body["id"]

    # PATCH 不带 api_key：密钥保持原密文不动
    resp = auth_client.patch(f"/api/sources/{body['id']}", json={"name": "改名"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "改名"
    assert resp.json()["api_key_hint"].endswith("3456")

    # PATCH api_key 空串 = 不改
    resp = auth_client.patch(f"/api/sources/{body['id']}", json={"api_key": ""})
    assert resp.status_code == 200
    assert resp.json()["api_key_hint"].endswith("3456")

    # PATCH 换密钥：尾4位跟着变
    resp = auth_client.patch(
        f"/api/sources/{body['id']}", json={"api_key": "sk-newkey9999"}
    )
    assert resp.status_code == 200
    assert resp.json()["api_key_hint"].endswith("9999")

    # 原密钥不在响应里出现
    assert "sk-newkey9999" not in json.dumps(resp.json(), ensure_ascii=False)


def test_patch_nonexistent_404(auth_client):
    resp = auth_client.patch("/api/sources/999", json={"name": "x"})
    assert resp.status_code == 404


def test_delete_source(auth_client):
    body = _create(auth_client).json()
    resp = auth_client.delete(f"/api/sources/{body['id']}")
    assert resp.status_code == 200
    assert auth_client.get("/api/sources").json()["sources"] == []
    resp = auth_client.delete(f"/api/sources/{body['id']}")
    assert resp.status_code == 404


def _mock_transport(handler):  # type: ignore[no-untyped-def]
    return httpx.MockTransport(handler)


def test_connectivity_success_updates_status(auth_client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        assert request.headers["authorization"] == "Bearer sk-abcdef123456"
        return httpx.Response(200, json={"data": [{"id": "gpt-test"}, {"id": "gpt-2"}]})

    monkeypatch.setattr(sources_module, "_TRANSPORT", _mock_transport(handler))
    body = _create(auth_client).json()

    resp = auth_client.post(f"/api/sources/{body['id']}/test")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "detail": "连通正常，2 个模型"}


def test_connectivity_auth_failure_reports_detail(auth_client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid key"}})

    monkeypatch.setattr(sources_module, "_TRANSPORT", _mock_transport(handler))
    body = _create(auth_client).json()

    resp = auth_client.post(f"/api/sources/{body['id']}/test")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "401" in data["detail"]


def test_connectivity_network_error(auth_client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(sources_module, "_TRANSPORT", _mock_transport(handler))
    body = _create(auth_client).json()

    resp = auth_client.post(f"/api/sources/{body['id']}/test")
    data = resp.json()
    assert data["ok"] is False
    assert "连接失败" in data["detail"]


def test_connectivity_anthropic_appends_v1(auth_client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        # base_url 不带 /v1 时应请求 {base}/v1/models，并带 x-api-key 头
        assert request.url.path == "/v1/models"
        assert request.headers["x-api-key"] == "sk-anthropic-key1"
        return httpx.Response(200, json={"data": [{"id": "claude-x"}]})

    monkeypatch.setattr(sources_module, "_TRANSPORT", _mock_transport(handler))
    body = _create(
        auth_client,
        format="anthropic",
        base_url="https://api.anthropic.com",
        api_key="sk-anthropic-key1",
    ).json()

    resp = auth_client.post(f"/api/sources/{body['id']}/test")
    assert resp.json()["ok"] is True


def test_connectivity_anthropic_v1_base_not_doubled(auth_client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr(sources_module, "_TRANSPORT", _mock_transport(handler))
    body = _create(
        auth_client,
        format="anthropic",
        base_url="https://proxy.example.com/v1",
        api_key="sk-key",
    ).json()
    resp = auth_client.post(f"/api/sources/{body['id']}/test")
    assert resp.json()["ok"] is True


def test_connectivity_requires_login(client):
    resp = client.post("/api/sources/1/test")
    assert resp.status_code == 401
