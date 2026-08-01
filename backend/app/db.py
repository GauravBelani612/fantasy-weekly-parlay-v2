from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs() -> dict:
    if settings.is_sqlite:
        # SQLite has no pooling story worth configuring and rejects pool sizing args.
        return {}
    # Neon closes idle connections; recycle well inside that window and pre-ping.
    return {"pool_size": 5, "max_overflow": 5, "pool_pre_ping": True, "pool_recycle": 300}


engine = create_async_engine(settings.database_url, future=True, **_engine_kwargs())

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
