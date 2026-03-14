#!/usr/bin/env python3
from __future__ import annotations

import asyncio

from dotenv import load_dotenv

from saleacc_bot.db import init_db

load_dotenv()


async def main() -> None:
    await init_db()
    print("ChatGPT stock import from CSV is deprecated. Fill Google Sheets inventory manually.")


if __name__ == "__main__":
    asyncio.run(main())
