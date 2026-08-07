from fastapi.testclient import TestClient


def test_openapi_json_documents_selected_api_contracts(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

    schema = response.json()
    assert schema["info"]["title"] == "TaskHub API"
    assert "task management API" in schema["info"]["description"]
    assert schema["info"]["version"] == "0.1.0"

    tag_descriptions = {tag["name"]: tag["description"] for tag in schema["tags"]}
    assert tag_descriptions["auth"] == (
        "Registration, login, refresh-token rotation, and logout."
    )
    assert tag_descriptions["tasks"] == (
        "Project task CRUD, filtering, assignment, and status updates."
    )
    assert tag_descriptions["workspaces"] == (
        "Workspace CRUD and membership management."
    )

    security_scheme = schema["components"]["securitySchemes"]["OAuth2PasswordBearer"]
    assert security_scheme["type"] == "oauth2"
    assert security_scheme["flows"]["password"]["tokenUrl"] == "/api/v1/auth/login"

    login_operation = schema["paths"]["/api/v1/auth/login"]["post"]
    assert "security" not in login_operation
    assert "username field" in login_operation["description"]
    assert login_operation["responses"]["401"]["description"] == (
        "Email or password is incorrect."
    )
    assert login_operation["responses"]["403"]["description"] == (
        "The user account is inactive."
    )

    task_list_operation = schema["paths"]["/api/v1/projects/{project_id}/tasks"]["get"]
    assert task_list_operation["security"] == [{"OAuth2PasswordBearer": []}]
    assert task_list_operation["responses"]["401"]["description"] == (
        "Missing or invalid Bearer access token."
    )
    assert task_list_operation["responses"]["404"]["description"] == (
        "Project was not found or is hidden from the user."
    )
    assert (
        task_list_operation["responses"]["422"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/HTTPValidationError"
    )

    task_parameters = {
        parameter["name"]: parameter for parameter in task_list_operation["parameters"]
    }
    assert task_parameters["project_id"]["description"] == (
        "Project whose tasks are listed."
    )
    assert task_parameters["status"]["description"] == (
        "Filter by task workflow status."
    )
    assert task_parameters["priority"]["description"] == "Filter by task priority."
    assert task_parameters["assignee_id"]["description"] == (
        "Filter to tasks assigned to this user ID."
    )
    assert task_parameters["page"]["description"] == "Page number, starting at 1."
    assert task_parameters["limit"]["description"] == (
        "Maximum tasks per page, from 1 through 100."
    )

    add_member_operation = schema["paths"]["/api/v1/workspaces/{workspace_id}/members"][
        "post"
    ]
    assert add_member_operation["responses"]["404"]["description"] == (
        "Workspace or target user was not found."
    )
    assert add_member_operation["responses"]["409"]["description"] == (
        "Membership already exists or target user is inactive."
    )


def test_swagger_ui_is_served(client: TestClient) -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "SwaggerUIBundle" in response.text
    assert "TaskHub API - Swagger UI" in response.text


def test_redoc_is_served(client: TestClient) -> None:
    response = client.get("/redoc")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'spec-url="/openapi.json"' in response.text
    assert "TaskHub API - ReDoc" in response.text
