#!/usr/bin/env python3
from __future__ import annotations

import asyncio

from dotenv import load_dotenv

from saleacc_bot.services.sheets_store import get_sheets_store

load_dotenv()


async def main() -> None:
    if not await get_sheets_store().ensure_schema():
        raise SystemExit("Google Sheet schema initialization failed. Check the error above.")
    print("Google Sheet schema is ready: worksheet orders")


if __name__ == "__main__":
    asyncio.run(main())
