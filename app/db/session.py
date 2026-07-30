from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

AsyncSessionFactory = async_sessionmaker[AsyncSession]


def create_database_engine(database_url: str) -> AsyncEngine:
    """Create the async SQLAlchemy engine without opening a connection."""
    return create_async_engine(database_url)


def create_database_session_factory(engine: AsyncEngine) -> AsyncSessionFactory:
    """Create the async session factory for request-scoped sessions."""
    return async_sessionmaker(bind=engine, expire_on_commit=False)
