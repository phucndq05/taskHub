# TaskHub

TaskHub is a FastAPI-based task management Web API developed as the sample application for the Tech Stack Python - FastAPI module.

## Scope

The project implements a backend API only. No frontend application is included in this module.

Planned capabilities include:

- JWT authentication with access and refresh tokens
- User profile management
- Workspaces and member roles
- Projects, tasks, labels, and comments
- Task filtering and pagination
- Redis caching with invalidation
- Background email notification on task assignment
- Resource-level RBAC
- Swagger UI and ReDoc documentation
- Docker Compose for the API, PostgreSQL, and Redis

## Planned stack

- Python 3.11
- FastAPI 0.111+
- Pydantic v2 and pydantic-settings
- SQLAlchemy 2.x async and asyncpg
- Alembic
- PostgreSQL 16
- Redis 7
- Docker and Docker Compose
- Ruff, mypy, and pytest

## Architecture overview

```text
Router -> Service -> Repository -> AsyncSession -> PostgreSQL
```

Routers handle HTTP concerns. Services contain business rules and transaction boundaries. Repositories contain database access and do not commit transactions.

## Project status

The repository is currently in the preparation stage. Implementation will be delivered through feature-scoped pull requests during the eight-day module.

## Development

Setup, test, lint, migration, Docker, and API documentation commands will be added and verified as the application is implemented.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the project workflow and quality rules.
