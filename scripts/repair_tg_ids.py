#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from saleacc_bot.config import get_settings
from saleacc_bot.db import _normalize_database_url

load_dotenv()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repair Telegram ID column types and unblock selected users."
    )
    parser.add_argument(
        "--user-id",
        type=int,
        action="append",
        default=[],
        help="Telegram user id to set is_blocked=false (can be repeated).",
    )
    return parser.parse_args()


async def _repair(user_ids: list[int]) -> None:
    settings = get_settings()
    engine = create_async_engine(
        _normalize_database_url(settings.database_url),
        future=True,
        echo=False,
    )

    async with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
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
            print("Postgres: checked/updated tg id columns to BIGINT.")

        elif conn.dialect.name == "sqlite":
            print("SQLite detected: BIGINT migration not required.")
        else:
            print(f"Dialect '{conn.dialect.name}' not explicitly handled; skipping type migration.")

        if user_ids:
            for user_id in user_ids:
                await conn.execute(
                    text(
                        """
                        UPDATE bot_users
                        SET is_blocked = false
                        WHERE tg_user_id = :uid
                        """
                    ),
                    {"uid": user_id},
                )
            print(f"Unblocked users (if existed): {', '.join(str(x) for x in user_ids)}")

    await engine.dispose()
    print("Done.")


def main() -> None:
    args = _parse_args()
    asyncio.run(_repair(args.user_id))


if __name__ == "__main__":
    main()
