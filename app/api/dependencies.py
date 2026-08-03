from collections.abc import AsyncGenerator
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.session import AsyncSessionFactory
from app.models.user import User
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.task import TaskRepository
from app.repositories.user import UserRepository
from app.services.auth import (
    AuthService,
    InactiveUserError,
    InvalidAccessTokenError,
)
from app.services.task import TaskService

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
