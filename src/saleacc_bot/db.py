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
    if "${{" in url and "}}" in url:
        raise RuntimeError("DATABASE_URL contains unresolved template reference")
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
        await _ensure_bot_user_columns(conn)
        await _ensure_product_columns(conn)
        await _ensure_order_columns(conn)


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
        END
        $$;
        """
    )


async def _ensure_bot_user_columns(conn: AsyncConnection) -> None:
    await _add_column_if_missing(conn, "bot_users", "email", "VARCHAR(255)")


async def _ensure_product_columns(conn: AsyncConnection) -> None:
    await _add_column_if_missing(conn, "products", "price_kopecks", "INTEGER DEFAULT 50000")
    await _add_column_if_missing(conn, "products", "sort_order", "INTEGER DEFAULT 100")
    await _backfill_column_if_present(
        conn,
        table="products",
        column="price_kopecks",
        expression="50000",
        condition="price_kopecks IS NULL",
    )
    await _backfill_column_if_present(
        conn,
        table="products",
        column="sort_order",
        expression="100",
        condition="sort_order IS NULL",
    )


async def _ensure_order_columns(conn: AsyncConnection) -> None:
    await _add_column_if_missing(conn, "orders", "customer_email", "VARCHAR(255)")
    await _add_column_if_missing(conn, "orders", "product_slug", "VARCHAR(64)")
    await _add_column_if_missing(conn, "orders", "product_title", "VARCHAR(128)")
    await _add_column_if_missing(conn, "orders", "provider_payment_id", "VARCHAR(255)")
    await _add_column_if_missing(conn, "orders", "provider_status", "VARCHAR(64)")
    await _add_column_if_missing(conn, "orders", "payment_confirmation_url", "TEXT")
    await _add_column_if_missing(conn, "orders", "assigned_stock_item_id", "VARCHAR(128)")
    await _add_column_if_missing(conn, "orders", "cancellation_reason", "VARCHAR(255)")
    await _add_column_if_missing(conn, "orders", "paid_at", "TIMESTAMP")
    await _add_column_if_missing(conn, "orders", "reserved_until", "TIMESTAMP")
    await _add_column_if_missing(conn, "orders", "cancelled_at", "TIMESTAMP")
    await _add_column_if_missing(conn, "orders", "delivered_at", "TIMESTAMP")
    await _backfill_column_if_present(
        conn,
        table="orders",
        column="customer_email",
        expression="''",
        condition="customer_email IS NULL",
    )
    await _backfill_column_if_present(
        conn,
        table="orders",
        column="product_slug",
        expression="''",
        condition="product_slug IS NULL",
    )
    await _backfill_column_if_present(
        conn,
        table="orders",
        column="product_title",
        expression="''",
        condition="product_title IS NULL",
    )


async def _add_column_if_missing(
    conn: AsyncConnection,
    table_name: str,
    column_name: str,
    column_sql: str,
) -> None:
    if await _column_exists(conn, table_name, column_name):
        return
    await conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql};")


async def _backfill_column_if_present(
    conn: AsyncConnection,
    *,
    table: str,
    column: str,
    expression: str,
    condition: str,
) -> None:
    if not await _column_exists(conn, table, column):
        return
    await conn.exec_driver_sql(f"UPDATE {table} SET {column} = {expression} WHERE {condition};")


async def _column_exists(conn: AsyncConnection, table_name: str, column_name: str) -> bool:
    if conn.dialect.name == "postgresql":
        result = await conn.exec_driver_sql(
            f"""
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = '{table_name}'
              AND column_name = '{column_name}'
            """
        )
        return result.first() is not None

    if conn.dialect.name == "sqlite":
        result = await conn.exec_driver_sql(f"PRAGMA table_info({table_name});")
        rows = result.fetchall()
        return any(str(row[1]) == column_name for row in rows)

    raise RuntimeError(f"Unsupported database dialect: {conn.dialect.name}")
