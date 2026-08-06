# TaskHub

TaskHub is a FastAPI task-management Web API built as the sample application for
the Tech Stack Python - FastAPI module. This repository contains the backend API
only; no frontend is included.

## Current capabilities

- FastAPI application with lifespan handling and versioned routes under `/api/v1`
- Dependency injection and Pydantic v2 request/response schemas
- `GET /health`, Swagger UI, and ReDoc
- Layered `Router -> Service -> Repository` structure
- Authentication with register, login, refresh rotation, logout, and current-user
  lookup
- User profile and password workflows
- Workspace CRUD and membership management with `OWNER`, `EDITOR`, and `VIEWER`
  roles
- Project CRUD and archive lifecycle with safe delete checks
- Persisted project-scoped Task CRUD backed by PostgreSQL
- Project-scoped labels and task-label attach/detach workflows
- Task comments with role and author-based deletion rules
- Redis caching for authorized project-scoped Task lists with 60-second TTL
- Background task-assignment email through FastAPI `BackgroundTasks`
- Resource authorization with system `ADMIN` override and workspace-role checks
- SQLAlchemy 2.x async configuration with request-scoped `AsyncSession`
- PostgreSQL 16 models for the TaskHub domain
- Alembic initial migration for the current schema
- Ruff, mypy, pytest, Dockerfile, and Docker Compose baseline

## Tech stack

- Python 3.11
- FastAPI 0.111+
- Pydantic v2 and pydantic-settings
- SQLAlchemy 2.x async and asyncpg
- PostgreSQL 16
- Redis
- Alembic
- Uvicorn
- Ruff, mypy, pytest, HTTPX
- Docker and Docker Compose

## Architecture

The target database-backed architecture is:

```text
Router -> Service -> Repository -> AsyncSession -> PostgreSQL
```

Routers handle HTTP concerns. Services coordinate business rules and transaction
boundaries. Repositories contain persistence queries and do not commit.

## Project structure

```text
app/api/          HTTP dependencies and versioned routers
app/core/         settings and shared application configuration
app/db/           async engine, session, Base, and mixins
app/models/       SQLAlchemy models and enums
app/repositories/ persistence implementations
app/schemas/      Pydantic request and response schemas
app/services/     business rules and transaction coordination
alembic/          migration environment and revisions
tests/            API, settings, session, metadata, and migration tests
```

## Local setup

Create and activate the Python 3.11 environment:

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

Create local environment configuration from the safe example:

```zsh
cp .env.example .env
```

Do not commit `.env` or real credentials.

Task list caching uses:

- `REDIS_URL`, for example `redis://localhost:6379/0`
- `TASK_LIST_CACHE_TTL_SECONDS`, default `60`

`GET /api/v1/projects/{project_id}/tasks` is cached only after authentication,
active-user checks, project lookup, and resource authorization succeed. Redis is
an optimization; PostgreSQL remains the source of truth if Redis is unavailable.

Task assignment email uses FastAPI `BackgroundTasks`. PostgreSQL commits and
task-list cache invalidation complete before the email task is scheduled. SMTP
delivery failures are logged after commit and do not roll back assignments or
change successful API responses.

SMTP is disabled when `SMTP_HOST` is empty. To enable local SMTP delivery, set:

- `SMTP_HOST`
- `SMTP_PORT`, default `1025`
- `SMTP_USERNAME`, optional but must be paired with `SMTP_PASSWORD`
- `SMTP_PASSWORD`, optional but must be paired with `SMTP_USERNAME`
- `SMTP_FROM_EMAIL`, default `no-reply@example.com`
- `SMTP_USE_STARTTLS`, default `false`
- `SMTP_TIMEOUT_SECONDS`, default `10`

## Database and migrations

Start PostgreSQL:

```zsh
docker compose up -d db
```

Apply the current schema:

```zsh
alembic upgrade head
```

Useful migration commands:

```zsh
alembic current
alembic check
alembic history
```

Every schema change must include a reviewed Alembic migration with verified
upgrade and downgrade behavior.

## Run locally

```zsh
uvicorn app.main:app --reload
```

Open:

- `http://localhost:8000/health`
- `http://localhost:8000/docs`
- `http://localhost:8000/redoc`

## Current API

```http
GET    /health
POST   /api/v1/auth/register
POST   /api/v1/auth/login
POST   /api/v1/auth/refresh
POST   /api/v1/auth/logout
GET    /api/v1/users/me
PATCH  /api/v1/users/me
POST   /api/v1/users/me/password
POST   /api/v1/workspaces
GET    /api/v1/workspaces
GET    /api/v1/workspaces/{workspace_id}
PATCH  /api/v1/workspaces/{workspace_id}
DELETE /api/v1/workspaces/{workspace_id}
GET    /api/v1/workspaces/{workspace_id}/members
POST   /api/v1/workspaces/{workspace_id}/members
PATCH  /api/v1/workspaces/{workspace_id}/members/{user_id}
DELETE /api/v1/workspaces/{workspace_id}/members/{user_id}
POST   /api/v1/workspaces/{workspace_id}/projects
GET    /api/v1/workspaces/{workspace_id}/projects
GET    /api/v1/projects/{project_id}
PATCH  /api/v1/projects/{project_id}
PATCH  /api/v1/projects/{project_id}/archive
DELETE /api/v1/projects/{project_id}
POST   /api/v1/projects/{project_id}/tasks
GET    /api/v1/projects/{project_id}/tasks
GET    /api/v1/tasks/{task_id}
PATCH  /api/v1/tasks/{task_id}
DELETE /api/v1/tasks/{task_id}
POST   /api/v1/projects/{project_id}/labels
GET    /api/v1/projects/{project_id}/labels
GET    /api/v1/labels/{label_id}
PATCH  /api/v1/labels/{label_id}
DELETE /api/v1/labels/{label_id}
POST   /api/v1/tasks/{task_id}/labels/{label_id}
DELETE /api/v1/tasks/{task_id}/labels/{label_id}
POST   /api/v1/tasks/{task_id}/comments
DELETE /api/v1/comments/{comment_id}
```

Swagger UI and ReDoc are the source for detailed request and response schemas.

## Roles

TaskHub has a system-level `ADMIN` override. Normal resource access is controlled
by workspace membership:

- `OWNER`: workspace administration, project administration, and task, label, and
  comment workflows
- `EDITOR`: project writes plus task, label, and comment workflows
- `VIEWER`: permitted read operations only

## Quality checks

```zsh
ruff format --check .
ruff check .
mypy app
pytest
```

## Docker

Validate the current Compose file:

```zsh
docker compose config
```

For now, use Docker Compose only to start PostgreSQL:

```zsh
docker compose up -d db
```

Then run the API from the host environment:

```zsh
uvicorn app.main:app --reload
```

Docker API startup, automatic migration wiring, Redis service wiring, and local
email service wiring will be added in later focused changes.

## Current limitations

- Docker does not yet run migrations automatically.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow.
