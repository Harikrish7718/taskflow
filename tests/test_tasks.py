def test_create_and_list_task(client, auth_headers):
    resp = client.post("/tasks", json={"title": "Write tests"}, headers=auth_headers)
    assert resp.status_code == 201
    task_id = resp.json()["id"]

    resp = client.get("/tasks", headers=auth_headers)
    assert resp.status_code == 200
    titles = [t["title"] for t in resp.json()]
    assert "Write tests" in titles
    assert resp.json()[0]["id"] == task_id


def test_task_list_is_cached(client, auth_headers):
    """Second call should return cached data even without hitting the DB again."""
    client.post("/tasks", json={"title": "Cache me"}, headers=auth_headers)

    first = client.get("/tasks", headers=auth_headers).json()
    second = client.get("/tasks", headers=auth_headers).json()  # served from cache
    assert first == second


def test_create_invalidates_cache(client, auth_headers):
    client.post("/tasks", json={"title": "First"}, headers=auth_headers)
    client.get("/tasks", headers=auth_headers)  # populate cache

    client.post("/tasks", json={"title": "Second"}, headers=auth_headers)  # should invalidate
    resp = client.get("/tasks", headers=auth_headers)
    titles = [t["title"] for t in resp.json()]
    assert "First" in titles and "Second" in titles


def test_get_single_task_not_found(client, auth_headers):
    resp = client.get("/tasks/9999", headers=auth_headers)
    assert resp.status_code == 404


def test_update_task_status(client, auth_headers):
    task_id = client.post("/tasks", json={"title": "Ship it"}, headers=auth_headers).json()["id"]
    resp = client.patch(f"/tasks/{task_id}", json={"status": "done"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"


def test_delete_task(client, auth_headers):
    task_id = client.post("/tasks", json={"title": "Temp"}, headers=auth_headers).json()["id"]
    resp = client.delete(f"/tasks/{task_id}", headers=auth_headers)
    assert resp.status_code == 204

    resp = client.get(f"/tasks/{task_id}", headers=auth_headers)
    assert resp.status_code == 404


def test_tasks_require_auth(client):
    resp = client.get("/tasks")
    assert resp.status_code == 401


def test_users_cannot_see_others_tasks(client):
    client.post("/auth/signup", json={"email": "u1@example.com", "password": "pw12345"})
    t1 = client.post("/auth/login", data={"username": "u1@example.com", "password": "pw12345"}).json()["access_token"]
    client.post("/tasks", json={"title": "U1 task"}, headers={"Authorization": f"Bearer {t1}"})

    client.post("/auth/signup", json={"email": "u2@example.com", "password": "pw12345"})
    t2 = client.post("/auth/login", data={"username": "u2@example.com", "password": "pw12345"}).json()["access_token"]
    resp = client.get("/tasks", headers={"Authorization": f"Bearer {t2}"})

    assert resp.json() == []
