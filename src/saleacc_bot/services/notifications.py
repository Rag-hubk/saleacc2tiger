from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import FSInputFile

from saleacc_bot.config import Settings
from saleacc_bot.models import Order, StockAccount
from saleacc_bot.services.stock import order_needs_auto_delivery
from saleacc_bot.ui import format_price, main_menu_image_path, main_menu_payload


async def notify_order_paid(
    bot: Bot,
    settings: Settings,
    order: Order,
    *,
    stock_account: StockAccount | None = None,
) -> None:
    try:
        user_text = _build_user_paid_text(order, stock_account=stock_account)
        await bot.send_message(
            chat_id=order.tg_user_id,
            text=user_text,
            parse_mode="HTML",
        )
        main_text, main_keyboard = main_menu_payload(settings, order.tg_user_id)
        await bot.send_photo(
            chat_id=order.tg_user_id,
            photo=FSInputFile(str(main_menu_image_path())),
            caption=main_text,
            reply_markup=main_keyboard,
            parse_mode="HTML",
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        pass

    for admin_id in settings.admin_ids:
        try:
            username = f"@{order.tg_username}" if order.tg_username else "-"
            mode = "Автовыдача GPT" if order_needs_auto_delivery(order) else "Ручная выдача Gemini"
            delivery = stock_account.item_id if stock_account is not None else "manual"
            await bot.send_message(
                chat_id=admin_id,
                text=(
                    "<b>Новая оплата</b>\n\n"
                    f"Тариф: <b>{order.product_title}</b>\n"
                    f"Режим: <b>{mode}</b>\n"
                    f"Сумма: <code>{format_price(order.total_price)}</code>\n"
                    f"Покупатель: <code>{order.tg_user_id}</code>\n"
                    f"Username: {username}\n"
                    f"E-mail: <code>{order.customer_email}</code>\n"
                    f"Заказ: <code>{order.id}</code>\n"
                    f"Выдача: <code>{delivery}</code>"
                ),
                parse_mode="HTML",
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            continue


def _build_user_paid_text(order: Order, *, stock_account: StockAccount | None) -> str:
    if order_needs_auto_delivery(order) and stock_account is not None:
        note_line = f"\nПримечание: <code>{stock_account.note}</code>" if stock_account.note else ""
        return (
            "<b>Оплата получена, аккаунт выдан</b>\n\n"
            f"Тариф: <b>{order.product_title}</b>\n"
            f"Сумма: <code>{format_price(order.total_price)}</code>\n"
            f"Логин: <code>{stock_account.access_login}</code>\n"
            f"Пароль: <code>{stock_account.access_secret}</code>"
            f"{note_line}\n\n"
            "Аккаунт персональный. Если понадобится помощь с входом или VPN, напишите в поддержку."
        )

    if order_needs_auto_delivery(order):
        return (
            "<b>Оплата получена</b>\n\n"
            f"Тариф: <b>{order.product_title}</b>\n"
            f"Сумма: <code>{format_price(order.total_price)}</code>\n\n"
            "Платеж подтвержден, но аккаунт не выдан автоматически. "
            "Мы уже получили уведомление и отправим доступ в бота вручную."
        )

    return (
        "<b>Оплата получена</b>\n\n"
        f"Тариф: <b>{order.product_title}</b>\n"
        f"Сумма: <code>{format_price(order.total_price)}</code>\n"
        f"E-mail: <code>{order.customer_email}</code>\n\n"
        "Выдача аккаунта по этому тарифу выполняется вручную. "
        "Доступ придет в этого бота в течение 1-24 часов."
    )
