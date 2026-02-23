#!/usr/bin/env python3
from __future__ import annotations

import asyncio

from dotenv import load_dotenv

from saleacc_bot.services.inventory import get_sheets_store

load_dotenv()


async def main() -> None:
    await get_sheets_store().ensure_schema()
    print("Google Sheet schema is ready: worksheets inventory + sales")


if __name__ == "__main__":
    asyncio.run(main())
