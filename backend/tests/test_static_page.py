def test_root_serves_login_page_anonymously(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_login_page_wires_api(client):
    body = client.get("/").text
    # 表单与接口存在
    assert "/api/auth/login" in body
    assert "/api/auth/session" in body
    # 前端 fetch 必须带 CSRF 头（中间件要求）
    assert "X-Requested-With" in body
    assert "XMLHttpRequest" in body
