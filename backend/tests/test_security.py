from app.db import connect
from app.security import redact, seal, unseal


def test_login_session_csrf_and_scope(admin):
    admin.headers.pop("x-csrf-token")
    assert admin.post("/api/v1/keys", json={"name": "bad"}).status_code == 403
    csrf = admin.get("/api/v1/auth/me").json()["csrf"]
    admin.headers["x-csrf-token"] = csrf
    response = admin.post("/api/v1/keys", json={"name": "monitor", "scope": "read"})
    assert response.status_code == 201
    key = response.json()
    admin.cookies.clear()
    admin.headers["Authorization"] = "Bearer " + key["token"]
    assert admin.get("/api/v1/topology").status_code == 200
    assert admin.post("/api/v1/keys", json={"name": "bad"}).status_code == 403
    with connect() as db:
        assert key["token"] not in str([tuple(r) for r in db.execute("SELECT * FROM api_keys")])


def test_vault_never_returns_secret(admin):
    secret = "private-test-password"
    response = admin.post(
        "/api/v1/credentials", json={"name": "Root", "kind": "password", "secret": secret}
    )
    assert response.status_code == 201
    assert secret not in admin.get("/api/v1/credentials").text
    with connect() as db:
        value = db.execute("SELECT encrypted FROM credentials").fetchone()[0]
        assert secret not in value
        assert unseal(value)["secret"] == secret


def test_validation_errors_do_not_echo_secrets(admin):
    response = admin.post(
        "/api/v1/credentials", json={"name": "x", "kind": "bad", "secret": "sensitive-value"}
    )
    assert response.status_code == 422
    assert "sensitive-value" not in response.text


def test_failed_logins_are_counted(client):
    for _ in range(10):
        assert (
            client.post(
                "/api/v1/auth/login", json={"username": "admin", "password": "bad"}
            ).status_code
            == 401
        )
    assert (
        client.post("/api/v1/auth/login", json={"username": "admin", "password": "bad"}).status_code
        == 429
    )


def test_cipher_and_redaction(environment):
    assert unseal(seal({"value": "secret"})) == {"value": "secret"}
    assert "hello" not in redact("token=hello")
    assert "topsecret" not in redact("failure: topsecret", ["topsecret"])


def test_persian_errors(client):
    response = client.get("/api/v1/topology", headers={"Accept-Language": "fa"})
    assert response.status_code == 401
    assert any("\u0600" <= c <= "\u06ff" for c in response.json()["message"])
