def test_signup(client):
    resp = client.post("/auth/signup", json={"email": "a@example.com", "password": "pw12345"})
    assert resp.status_code == 201
    assert resp.json()["email"] == "a@example.com"
    assert "hashed_password" not in resp.json()  # never leak the hash


def test_signup_duplicate_email_rejected(client):
    client.post("/auth/signup", json={"email": "dup@example.com", "password": "pw12345"})
    resp = client.post("/auth/signup", json={"email": "dup@example.com", "password": "pw12345"})
    assert resp.status_code == 400


def test_login_success(client):
    client.post("/auth/signup", json={"email": "login@example.com", "password": "pw12345"})
    resp = client.post("/auth/login", data={"username": "login@example.com", "password": "pw12345"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_wrong_password_rejected(client):
    client.post("/auth/signup", json={"email": "wp@example.com", "password": "pw12345"})
    resp = client.post("/auth/login", data={"username": "wp@example.com", "password": "wrongpass"})
    assert resp.status_code == 401


def test_me_requires_auth(client):
    resp = client.get("/users/me")
    assert resp.status_code == 401


def test_me_with_valid_token(client, auth_headers):
    resp = client.get("/users/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "test@example.com"
