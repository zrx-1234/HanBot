"""GET/PUT /api/settings：默认值合并、类型与范围校验、登录保护。"""


def test_get_settings_returns_defaults(auth_client):
    st = auth_client.get("/api/settings").json()["settings"]
    # design §4.3 的默认值
    assert st["max_concurrent_tasks"] == 2
    assert st["max_steps"] == 50
    assert st["task_timeout_minutes"] == 30
    assert st["bash_timeout_seconds"] == 120
    assert st["sandbox_memory_mb"] == 512
    assert st["backup_retention"] == 14
    assert st["memory_token_budget"] == 1500
    assert st["review_time"] == "03:00"
    assert isinstance(st["system_prompt"], str) and st["system_prompt"]


def test_put_settings_merges_and_persists(auth_client):
    resp = auth_client.put("/api/settings", json={"settings": {"max_concurrent_tasks": 4}})
    assert resp.status_code == 200
    assert resp.json()["settings"]["max_concurrent_tasks"] == 4

    st = auth_client.get("/api/settings").json()["settings"]
    assert st["max_concurrent_tasks"] == 4
    assert st["max_steps"] == 50  # 未动的键保持默认


def test_settings_require_login(client):
    assert client.get("/api/settings").status_code == 401
    resp = client.put("/api/settings", json={"settings": {"max_steps": 10}})
    assert resp.status_code == 401


def test_put_rejects_unknown_key(auth_client):
    resp = auth_client.put("/api/settings", json={"settings": {"no_such_key": 1}})
    assert resp.status_code == 422


def test_put_rejects_wrong_type(auth_client):
    resp = auth_client.put(
        "/api/settings", json={"settings": {"max_concurrent_tasks": "three"}}
    )
    assert resp.status_code == 422


def test_put_rejects_out_of_range(auth_client):
    for bad in (0, -1, 11):
        resp = auth_client.put(
            "/api/settings", json={"settings": {"max_concurrent_tasks": bad}}
        )
        assert resp.status_code == 422, bad


def test_put_rejects_bad_review_time(auth_client):
    resp = auth_client.put("/api/settings", json={"settings": {"review_time": "3点"}})
    assert resp.status_code == 422
    resp = auth_client.put("/api/settings", json={"settings": {"review_time": "25:00"}})
    assert resp.status_code == 422
    resp = auth_client.put(
        "/api/settings", json={"settings": {"review_time": "03:30"}}
    )
    assert resp.status_code == 200
