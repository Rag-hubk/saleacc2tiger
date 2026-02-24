from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio.engine import AsyncConnection

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
        await _migrate_tg_id_columns_to_bigint(conn)
        await _migrate_order_checkout_columns(conn)


async def _migrate_tg_id_columns_to_bigint(conn: AsyncConnection) -> None:
    if conn.dialect.name != "postgresql":
        return
    await conn.exec_driver_sql(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'bot_users'
                  AND column_name = 'tg_user_id'
                  AND data_type = 'integer'
            ) THEN
                ALTER TABLE public.bot_users ALTER COLUMN tg_user_id TYPE BIGINT;
            END IF;

            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'orders'
                  AND column_name = 'tg_user_id'
                  AND data_type = 'integer'
            ) THEN
                ALTER TABLE public.orders ALTER COLUMN tg_user_id TYPE BIGINT;
            END IF;

            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'inventory_items'
                  AND column_name = 'reserved_by_tg_id'
                  AND data_type = 'integer'
            ) THEN
                ALTER TABLE public.inventory_items ALTER COLUMN reserved_by_tg_id TYPE BIGINT;
            END IF;
        END
        $$;
        """
    )


async def _migrate_order_checkout_columns(conn: AsyncConnection) -> None:
    if conn.dialect.name == "postgresql":
        await conn.exec_driver_sql(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'orders'
                      AND column_name = 'checkout_chat_id'
                ) THEN
                    ALTER TABLE public.orders ADD COLUMN checkout_chat_id BIGINT NULL;
                END IF;

                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'orders'
                      AND column_name = 'checkout_message_id'
                ) THEN
                    ALTER TABLE public.orders ADD COLUMN checkout_message_id INTEGER NULL;
                END IF;
            END
            $$;
            """
        )
        return

    if conn.dialect.name == "sqlite":
        result = await conn.exec_driver_sql("PRAGMA table_info(orders);")
        rows = result.fetchall()
        existing_columns = {str(row[1]) for row in rows}

        if "checkout_chat_id" not in existing_columns:
            await conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN checkout_chat_id BIGINT;")
        if "checkout_message_id" not in existing_columns:
            await conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN checkout_message_id INTEGER;")
