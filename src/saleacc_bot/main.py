from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from saleacc_bot.config import get_settings
from saleacc_bot.db import get_session, init_db
from saleacc_bot.handlers import admin, user
from saleacc_bot.services.catalog import seed_default_products
from saleacc_bot.services.sheets_store import get_sheets_store
from saleacc_bot.services.stock import cleanup_expired_reservations

logger = logging.getLogger(__name__)


async def start_polling() -> None:
    settings = get_settings()
    await init_db()

    async with get_session() as session:
        await seed_default_products(session)
        await cleanup_expired_reservations(session)

    await get_sheets_store().ensure_schema()

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    dp.include_router(admin.router)
    dp.include_router(user.router)

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        logger.info("Bot polling started")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


def run() -> None:
    asyncio.run(start_polling())


if __name__ == "__main__":
    run()
