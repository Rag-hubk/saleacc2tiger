#!/usr/bin/env python3
from __future__ import annotations

import asyncio

from dotenv import load_dotenv

from saleacc_bot.config import get_settings
from saleacc_bot.db import get_session, init_db
from saleacc_bot.services.stock import sync_chatgpt_stock

load_dotenv()


async def main() -> None:
    settings = get_settings()
    await init_db()
    async with get_session() as session:
        imported = await sync_chatgpt_stock(session, settings)
    print(f"ChatGPT stock synced: {imported} items")


if __name__ == "__main__":
    asyncio.run(main())
