from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from saleacc_bot.config import Settings
from saleacc_bot.models import Order
from saleacc_bot.ui import format_price, main_menu_payload


async def notify_order_paid(bot: Bot, settings: Settings, order: Order) -> None:
    try:
        await bot.send_message(
            chat_id=order.tg_user_id,
            text=(
                "<b>Оплата получена</b>\n\n"
                f"Тариф: <b>{order.product_title}</b>\n"
                f"Сумма: <code>{format_price(order.total_price)}</code>\n"
                f"E-mail: <code>{order.customer_email}</code>\n\n"
                "Заказ зафиксирован. Дальше можно выдать доступ вручную или связаться с клиентом."
            ),
            parse_mode="HTML",
        )
        main_text, main_keyboard = main_menu_payload(settings, order.tg_user_id)
        await bot.send_message(
            chat_id=order.tg_user_id,
            text=main_text,
            reply_markup=main_keyboard,
            parse_mode="HTML",
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        pass

    for admin_id in settings.admin_ids:
        try:
            username = f"@{order.tg_username}" if order.tg_username else "-"
            await bot.send_message(
                chat_id=admin_id,
                text=(
                    "<b>Новая оплата</b>\n\n"
                    f"Тариф: <b>{order.product_title}</b>\n"
                    f"Сумма: <code>{format_price(order.total_price)}</code>\n"
                    f"Покупатель: <code>{order.tg_user_id}</code>\n"
                    f"Username: {username}\n"
                    f"E-mail: <code>{order.customer_email}</code>\n"
                    f"Заказ: <code>{order.id}</code>"
                ),
                parse_mode="HTML",
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            continue
