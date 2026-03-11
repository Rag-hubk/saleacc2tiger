from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from saleacc_bot.config import get_settings
from saleacc_bot.db import get_session
from saleacc_bot.keyboards import admin_back_keyboard, admin_panel_keyboard
from saleacc_bot.services.orders import get_dashboard_stats, list_recent_orders
from saleacc_bot.services.users import get_audience_stats
from saleacc_bot.ui import format_order_status, format_price

router = Router(name="admin")
settings = get_settings()


def _is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


async def _safe_edit(callback: CallbackQuery, text: str, reply_markup) -> None:
    if callback.message is None:
        return
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise


async def _build_panel_text() -> str:
    async with get_session() as session:
        stats = await get_dashboard_stats(session)
        audience = await get_audience_stats(session)
    return (
        "<b>Админ-панель</b>\n\n"
        f"Всего заказов: <code>{stats['total_orders']}</code>\n"
        f"Оплачено: <code>{stats['paid_orders']}</code>\n"
        f"В ожидании: <code>{stats['pending_orders']}</code>\n"
        f"Выручка: <code>{format_price(int(stats['paid_revenue_kopecks']))}</code>\n"
        f"Пользователи: <code>{audience['known_users']}</code>"
    )


@router.message(Command("admin"))
async def on_admin_command(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    await message.answer(await _build_panel_text(), reply_markup=admin_panel_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "admin_panel")
async def on_admin_panel(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await _safe_edit(callback, await _build_panel_text(), admin_panel_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin_stats")
async def on_admin_stats(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    async with get_session() as session:
        stats = await get_dashboard_stats(session)

    lines = [
        "<b>Статистика продаж</b>",
        "",
        f"Всего заказов: <code>{stats['total_orders']}</code>",
        f"Оплачено: <code>{stats['paid_orders']}</code>",
        f"В ожидании: <code>{stats['pending_orders']}</code>",
        f"Выручка: <code>{format_price(int(stats['paid_revenue_kopecks']))}</code>",
        "",
        "<b>По продуктам:</b>",
    ]
    by_product = list(stats["by_product"])
    if by_product:
        lines.extend(
            f"- {row['title']}: {row['orders']} шт. / {format_price(int(row['revenue_kopecks']))}"
            for row in by_product
        )
    else:
        lines.append("Пока нет оплаченных заказов.")

    await _safe_edit(callback, "\n".join(lines), admin_back_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin_orders")
async def on_admin_orders(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    async with get_session() as session:
        orders = list(await list_recent_orders(session, limit=10))

    lines = ["<b>Последние заказы</b>", ""]
    if not orders:
        lines.append("Заказов пока нет.")
    else:
        for order in orders:
            lines.append(
                f"<code>{order.id[:8]}</code> | <b>{order.product_title}</b> | "
                f"{format_order_status(order.status)} | <code>{format_price(order.total_price)}</code>"
            )
            lines.append(f"E-mail: <code>{order.customer_email}</code> | tg: <code>{order.tg_user_id}</code>")
            lines.append("")

    await _safe_edit(callback, "\n".join(lines), admin_back_keyboard())
    await callback.answer()
