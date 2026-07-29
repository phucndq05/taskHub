# TaskHub

TaskHub is a FastAPI task management Web API developed as the sample
application for the Tech Stack Python - FastAPI module.

## Scope

The project implements a backend API only. No frontend application is included
in this module.

Day 1 provides the project bootstrap:

- FastAPI application with lifespan handling
- API version router under `/api/v1`
- Dependency injection
- `GET /health`
- In-memory sample Task CRUD
- Swagger UI and ReDoc
- Ruff, mypy, and pytest configuration
- Initial Dockerfile and Compose services for `api` and PostgreSQL 16 `db`

The Day 1 Task CRUD is temporary in-memory behavior to demonstrate the layered
architecture. It is not the complete Task feature. Sample tasks are stored only
in the API process memory, so they are lost when the API process or container
restarts. The PostgreSQL container does not store Day 1 sample tasks.

## Current Stack

- Python 3.11
- FastAPI
- Pydantic v2
- Uvicorn
- PostgreSQL 16 in Docker Compose as a baseline service
- Ruff, mypy, pytest, and HTTPX

## Architecture

```text
Router -> Service -> Repository
```

Routers handle HTTP concerns. Services coordinate the sample task flow.
Repositories manage the in-memory data store. Database integration is planned
for a later pull request.

## Local Setup

Create and activate the virtual environment with the selected Python
interpreter:

```zsh
/opt/homebrew/bin/python3.11 -m venv .venv
source .venv/bin/activate
python --version
```

Install dependencies:

```zsh
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

Run the API locally:

```zsh
uvicorn app.main:app --reload
```

Open:

- `http://localhost:8000/health`
- `http://localhost:8000/docs`
- `http://localhost:8000/redoc`

## API Endpoints

```http
GET    /health
POST   /api/v1/tasks
GET    /api/v1/tasks
GET    /api/v1/tasks/{task_id}
PATCH  /api/v1/tasks/{task_id}
DELETE /api/v1/tasks/{task_id}
```

## Quality Checks

```zsh
ruff format --check .
ruff check .
mypy app
pytest
```

## Docker

Validate the Compose file:

```zsh
docker compose config
```

Start the Day 1 stack:

```zsh
docker compose up --build
```

The PostgreSQL container is included as the initial Docker baseline. The API
does not connect to the database yet.

The default PostgreSQL credentials in `compose.yaml` and `.env.example` are
for local development only and must not be used in production.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the project workflow.
