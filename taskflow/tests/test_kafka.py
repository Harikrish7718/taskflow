def test_create_task_publishes_event(client, auth_headers, fake_kafka):
    client.post("/tasks", json={"title": "Event test"}, headers=auth_headers)

    assert len(fake_kafka.sent) == 1
    topic, payload = fake_kafka.sent[0]
    assert topic == "tasks-events"
    assert payload["event_type"] == "task.created"
    assert payload["title"] == "Event test"
    assert payload["status"] == "pending"


def test_update_task_publishes_event(client, auth_headers, fake_kafka):
    task_id = client.post("/tasks", json={"title": "T"}, headers=auth_headers).json()["id"]
    fake_kafka.sent.clear()  # ignore the creation event

    client.patch(f"/tasks/{task_id}", json={"status": "done"}, headers=auth_headers)

    assert len(fake_kafka.sent) == 1
    _, payload = fake_kafka.sent[0]
    assert payload["event_type"] == "task.updated"
    assert payload["status"] == "done"


def test_delete_task_publishes_event(client, auth_headers, fake_kafka):
    task_id = client.post("/tasks", json={"title": "T"}, headers=auth_headers).json()["id"]
    fake_kafka.sent.clear()

    client.delete(f"/tasks/{task_id}", headers=auth_headers)

    assert len(fake_kafka.sent) == 1
    _, payload = fake_kafka.sent[0]
    assert payload["event_type"] == "task.deleted"
    assert payload["task_id"] == task_id


def test_stats_endpoint_returns_shape(client):
    """
    /stats reads from Redis counters that only the consumer process writes.
    In this unit-test environment (no consumer running), we're just
    verifying the endpoint responds with the right shape - not that events
    were actually consumed. That end-to-end path is covered by the
    integration test that runs against a real broker in CI.
    """
    resp = client.get("/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert "tasks_created_total" in body
    assert "tasks_by_status" in body
    assert set(body["tasks_by_status"].keys()) == {"pending", "in_progress", "done"}
