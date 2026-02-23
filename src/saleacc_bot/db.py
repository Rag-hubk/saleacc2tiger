from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from saleacc_bot.config import get_settings
from saleacc_bot.models import Base

settings = get_settings()


def _normalize_database_url(raw_url: str) -> str:
    url = (raw_url or "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is empty")

    # Railway variable reference was not resolved.
    if "${{" in url and "}}" in url:
        raise RuntimeError(
            "DATABASE_URL contains unresolved Railway reference. "
            "Set it to ${{Postgres.DATABASE_URL}} (without quotes) in service/shared variables."
        )

    # SQLAlchemy async engine needs asyncpg driver.
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql+asyncpg://" + url[len("postgresql+psycopg2://") :]
    return url


engine = create_async_engine(_normalize_database_url(settings.database_url), future=True, echo=False)
SessionLocal = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@asynccontextmanager
async def get_session() -> AsyncSession:
    session = SessionLocal()
    try:
        yield session
    finally:
        await session.close()


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
