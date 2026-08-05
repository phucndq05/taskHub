from collections.abc import AsyncGenerator
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.session import AsyncSessionFactory
from app.models.user import User
from app.repositories.label import LabelRepository
from app.repositories.project import ProjectRepository
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.task import TaskRepository
from app.repositories.user import UserRepository
from app.repositories.workspace import WorkspaceRepository
from app.services.auth import (
    AuthService,
    InactiveUserError,
    InvalidAccessTokenError,
)
from app.services.label import LabelService
from app.services.project import ProjectService
from app.services.task import TaskService
from app.services.user import UserService
from app.services.workspace import WorkspaceService

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=False,
)
BEARER_HEADERS = {"WWW-Authenticate": "Bearer"}


def get_database_session_factory(request: Request) -> AsyncSessionFactory:
    """Return the app-level async session factory."""
    session_factory = getattr(request.app.state, "database_session_factory", None)
    if not isinstance(session_factory, async_sessionmaker):
        raise RuntimeError("Database session factory is not initialized.")
    return cast(AsyncSessionFactory, session_factory)


DatabaseSessionFactoryDep = Annotated[
    AsyncSessionFactory,
    Depends(get_database_session_factory),
]


async def get_database_session(
    session_factory: DatabaseSessionFactoryDep,
) -> AsyncGenerator[AsyncSession, None]:
    """Yield one request-scoped async database session."""
    session = session_factory()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


DatabaseSessionDep = Annotated[AsyncSession, Depends(get_database_session)]


def get_task_repository(session: DatabaseSessionDep) -> TaskRepository:
    """Create a task repository from the current request session."""
    return TaskRepository(session)


TaskRepositoryDep = Annotated[TaskRepository, Depends(get_task_repository)]


def get_user_repository(session: DatabaseSessionDep) -> UserRepository:
    """Create a user repository from the current request session."""
    return UserRepository(session)


UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]


def get_workspace_repository(session: DatabaseSessionDep) -> WorkspaceRepository:
    """Create a workspace repository from the current request session."""
    return WorkspaceRepository(session)


WorkspaceRepositoryDep = Annotated[
    WorkspaceRepository,
    Depends(get_workspace_repository),
]


def get_project_repository(session: DatabaseSessionDep) -> ProjectRepository:
    """Create a project repository from the current request session."""
    return ProjectRepository(session)


ProjectRepositoryDep = Annotated[
    ProjectRepository,
    Depends(get_project_repository),
]


def get_label_repository(session: DatabaseSessionDep) -> LabelRepository:
    """Create a label repository from the current request session."""
    return LabelRepository(session)


LabelRepositoryDep = Annotated[
    LabelRepository,
    Depends(get_label_repository),
]


def get_refresh_token_repository(
    session: DatabaseSessionDep,
) -> RefreshTokenRepository:
    """Create a refresh-token repository from the current request session."""
    return RefreshTokenRepository(session)


RefreshTokenRepositoryDep = Annotated[
    RefreshTokenRepository,
    Depends(get_refresh_token_repository),
]


def get_auth_service(
    user_repository: UserRepositoryDep,
    refresh_token_repository: RefreshTokenRepositoryDep,
    session: DatabaseSessionDep,
) -> AuthService:
    """Create an authentication service for the current request."""
    settings = get_settings()
    return AuthService(
        user_repository,
        refresh_token_repository,
        session,
        jwt_secret_key=settings.jwt_secret_key.get_secret_value(),
        jwt_algorithm=settings.jwt_algorithm,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def get_user_service(
    user_repository: UserRepositoryDep,
    refresh_token_repository: RefreshTokenRepositoryDep,
    session: DatabaseSessionDep,
) -> UserService:
    """Create a user service for the current request."""
    return UserService(user_repository, refresh_token_repository, session)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]

AccessTokenDep = Annotated[str | None, Depends(oauth2_scheme)]


async def get_current_user(
    token: AccessTokenDep,
    service: AuthServiceDep,
) -> User:
    """Resolve the active user represented by an access token."""
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers=BEARER_HEADERS,
        )

    try:
        return await service.get_current_user(token)
    except InvalidAccessTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers=BEARER_HEADERS,
        ) from exc
    except InactiveUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        ) from exc


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def get_current_active_user(current_user: CurrentUserDep) -> User:
    """Return the current active user."""
    return current_user


CurrentActiveUserDep = Annotated[User, Depends(get_current_active_user)]


def get_task_service(
    repository: TaskRepositoryDep,
    session: DatabaseSessionDep,
) -> TaskService:
    """Create a task service for the current request."""
    return TaskService(repository, session)


TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]


def get_workspace_service(
    workspace_repository: WorkspaceRepositoryDep,
    user_repository: UserRepositoryDep,
    session: DatabaseSessionDep,
) -> WorkspaceService:
    """Create a workspace service for the current request."""
    return WorkspaceService(workspace_repository, user_repository, session)


WorkspaceServiceDep = Annotated[WorkspaceService, Depends(get_workspace_service)]


def get_project_service(
    project_repository: ProjectRepositoryDep,
    workspace_repository: WorkspaceRepositoryDep,
    session: DatabaseSessionDep,
) -> ProjectService:
    """Create a project service for the current request."""
    return ProjectService(project_repository, workspace_repository, session)


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]


def get_label_service(
    label_repository: LabelRepositoryDep,
    workspace_repository: WorkspaceRepositoryDep,
    session: DatabaseSessionDep,
) -> LabelService:
    """Create a label service for the current request."""
    return LabelService(label_repository, workspace_repository, session)


LabelServiceDep = Annotated[LabelService, Depends(get_label_service)]
