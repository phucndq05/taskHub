from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.main import create_app


def test_create_task(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tasks",
        json={"title": "Draft project setup", "description": "Create skeleton app"},
    )

    assert response.status_code == 201
    body = response.json()
    task_id = UUID(body["id"])
    assert task_id.version == 4
    assert body["title"] == "Draft project setup"
    assert body["description"] == "Create skeleton app"


def test_list_tasks(client: TestClient) -> None:
    client.post("/api/v1/tasks", json={"title": "First task"})
    client.post("/api/v1/tasks", json={"title": "Second task"})

    response = client.get("/api/v1/tasks")

    assert response.status_code == 200
    assert [task["title"] for task in response.json()] == [
        "First task",
        "Second task",
    ]


def test_get_task(client: TestClient) -> None:
    created = client.post("/api/v1/tasks", json={"title": "Read task"}).json()

    response = client.get(f"/api/v1/tasks/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_partial_update_task(client: TestClient) -> None:
    created = client.post(
        "/api/v1/tasks",
        json={"title": "Original title", "description": "Original description"},
    ).json()

    response = client.patch(
        f"/api/v1/tasks/{created['id']}",
        json={"description": "Updated description"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": created["id"],
        "title": "Original title",
        "description": "Updated description",
    }


def test_partial_update_title_strips_whitespace_and_keeps_description(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/v1/tasks",
        json={"title": "Original title", "description": "Keep this description"},
    ).json()

    response = client.patch(
        f"/api/v1/tasks/{created['id']}",
        json={"title": "  Updated title  "},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": created["id"],
        "title": "Updated title",
        "description": "Keep this description",
    }


def test_partial_update_can_clear_description(client: TestClient) -> None:
    created = client.post(
        "/api/v1/tasks",
        json={"title": "Task with description", "description": "Remove this"},
    ).json()

    response = client.patch(
        f"/api/v1/tasks/{created['id']}",
        json={"description": None},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": created["id"],
        "title": "Task with description",
        "description": None,
    }


def test_delete_task(client: TestClient) -> None:
    created = client.post("/api/v1/tasks", json={"title": "Delete task"}).json()

    delete_response = client.delete(f"/api/v1/tasks/{created['id']}")
    get_response = client.get(f"/api/v1/tasks/{created['id']}")

    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert get_response.status_code == 404


def test_task_not_found_responses(client: TestClient) -> None:
    missing_task_id = uuid4()

    get_response = client.get(f"/api/v1/tasks/{missing_task_id}")
    patch_response = client.patch(
        f"/api/v1/tasks/{missing_task_id}",
        json={"title": "No task"},
    )
    delete_response = client.delete(f"/api/v1/tasks/{missing_task_id}")

    assert get_response.status_code == 404
    assert patch_response.status_code == 404
    assert delete_response.status_code == 404


def test_task_state_is_isolated_between_app_instances() -> None:
    with TestClient(create_app()) as first_client:
        first_client.post("/api/v1/tasks", json={"title": "Stored in first app"})
        assert len(first_client.get("/api/v1/tasks").json()) == 1

    with TestClient(create_app()) as second_client:
        response = second_client.get("/api/v1/tasks")

    assert response.status_code == 200
    assert response.json() == []


def test_create_rejects_blank_title(client: TestClient) -> None:
    response = client.post("/api/v1/tasks", json={"title": "   "})

    assert response.status_code == 422


def test_create_strips_title_whitespace(client: TestClient) -> None:
    response = client.post("/api/v1/tasks", json={"title": "  Trimmed title  "})

    assert response.status_code == 201
    assert response.json()["title"] == "Trimmed title"


def test_patch_rejects_null_title(client: TestClient) -> None:
    created = client.post("/api/v1/tasks", json={"title": "Keep title"}).json()

    response = client.patch(
        f"/api/v1/tasks/{created['id']}",
        json={"title": None},
    )

    assert response.status_code == 422


def test_unknown_request_fields_are_rejected(client: TestClient) -> None:
    create_response = client.post(
        "/api/v1/tasks",
        json={"title": "Valid title", "unknown": True},
    )
    patch_response = client.patch(
        f"/api/v1/tasks/{uuid4()}",
        json={"titel": "Wrong field"},
    )

    assert create_response.status_code == 422
    assert patch_response.status_code == 422


def test_invalid_task_id_format_returns_422(client: TestClient) -> None:
    response = client.get("/api/v1/tasks/not-a-uuid")

    assert response.status_code == 422
