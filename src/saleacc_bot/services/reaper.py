from __future__ import annotations

import asyncio

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from saleacc_bot.config import get_settings
from saleacc_bot.db import get_session
from saleacc_bot.services.orders import (
    cleanup_expired_reservations,
    clear_order_checkout_message,
    list_cancelled_orders_with_checkout_message,
)
from saleacc_bot.ui import main_menu_payload

REAPER_INTERVAL_SECONDS = 30


async def run_reservation_reaper_once(bot: Bot) -> None:
    settings = get_settings()
    async with get_session() as session:
        await cleanup_expired_reservations(session)
        orders = await list_cancelled_orders_with_checkout_message(session, limit=200)

        for order in orders:
            chat_id = order.checkout_chat_id
            message_id = order.checkout_message_id
            if chat_id is None or message_id is None:
                continue

            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except (TelegramBadRequest, TelegramForbiddenError):
                pass

            try:
                text, kb = main_menu_payload(settings, order.tg_user_id)
                await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb, parse_mode="HTML")
            except (TelegramBadRequest, TelegramForbiddenError):
                pass

            await clear_order_checkout_message(session, order_id=order.id, auto_commit=False)

        if orders:
            await session.commit()


async def reservation_reaper_loop(bot: Bot) -> None:
    while True:
        try:
            await run_reservation_reaper_once(bot)
        except Exception:
            # Keep loop alive; cleanup is best-effort.
            pass
        await asyncio.sleep(REAPER_INTERVAL_SECONDS)

