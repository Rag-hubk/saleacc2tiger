from __future__ import annotations

import asyncio
from pathlib import Path

from aiogram import Bot, Dispatcher

from saleacc_bot.config import get_settings
from saleacc_bot.db import get_session, init_db
from saleacc_bot.handlers import admin, payments, user
from saleacc_bot.services.catalog import seed_default_products
from saleacc_bot.services.inventory import get_sheets_store


async def start_polling() -> None:
    settings = get_settings()
    await init_db()

    async with get_session() as session:
        await seed_default_products(session)

    await get_sheets_store().ensure_schema()
    Path(settings.export_dir).mkdir(parents=True, exist_ok=True)

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    dp.include_router(admin.router)
    dp.include_router(payments.router)
    dp.include_router(user.router)

    await dp.start_polling(bot)


def run() -> None:
    asyncio.run(start_polling())


if __name__ == "__main__":
    run()
