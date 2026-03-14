#!/usr/bin/env python3
from __future__ import annotations

import asyncio

from dotenv import load_dotenv

from saleacc_bot.db import get_session, init_db
from saleacc_bot.services.catalog import seed_default_products
from saleacc_bot.services.sheets_store import get_sheets_store

load_dotenv()


async def main() -> None:
    await init_db()
    async with get_session() as session:
        await seed_default_products(session)
    if not await get_sheets_store().ensure_schema():
        raise SystemExit("Google Sheet schema initialization failed. Check the error above.")
    print("Google Sheet schema is ready: worksheets inventory and sales")


if __name__ == "__main__":
    asyncio.run(main())
