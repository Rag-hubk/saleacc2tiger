from __future__ import annotations

import asyncio
import html
from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from saleacc_bot.config import get_settings
from saleacc_bot.db import get_session
from saleacc_bot.keyboards import admin_back_keyboard, admin_broadcast_preview_keyboard, admin_panel_keyboard
from saleacc_bot.services.orders import get_dashboard_stats, get_order, list_recent_orders, mark_order_delivered
from saleacc_bot.services.sheets_store import get_sheets_store
from saleacc_bot.services.users import get_audience_stats, list_known_user_ids, mark_users_blocked
from saleacc_bot.states import AdminBroadcastStates, AdminDeliveryStates
from saleacc_bot.ui import format_order_status, format_price
from saleacc_bot.url_utils import is_valid_http_url

router = Router(name="admin")
settings = get_settings()
_broadcast_task: asyncio.Task | None = None


def _is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


async def _replace_admin_message(callback: CallbackQuery, text: str, reply_markup) -> None:
    chat_id = callback.message.chat.id if callback.message is not None else callback.from_user.id
    if callback.message is not None:
        with suppress(TelegramBadRequest):
            await callback.message.delete()
    await callback.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode="HTML")


def _message_html(message: Message) -> str:
    if message.html_text:
        return message.html_text.strip()
    return html.escape((message.text or "").strip())


def _parse_broadcast_buttons(raw: str) -> InlineKeyboardMarkup | None:
    normalized = raw.strip()
    if not normalized or normalized.lower() in {"-", "skip", "пропустить", "нет"}:
        return None

    rows: list[list[InlineKeyboardButton]] = []
    current_row: list[InlineKeyboardButton] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            if current_row:
                rows.append(current_row)
                current_row = []
            continue

        if "|" not in stripped:
            raise ValueError("Каждая кнопка должна быть в формате: Текст | https://example.com")
        text, url = [part.strip() for part in stripped.split("|", maxsplit=1)]
        if not text:
            raise ValueError("У кнопки отсутствует текст.")
        if not is_valid_http_url(url):
            raise ValueError(f"Некорректный URL для кнопки: {url}")
        current_row.append(InlineKeyboardButton(text=text, url=url))

    if current_row:
        rows.append(current_row)

    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def _send_broadcast_preview(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    preview_text = str(data.get("broadcast_text") or "").strip()
    buttons_raw = str(data.get("broadcast_buttons_raw") or "")
    try:
        preview_markup = _parse_broadcast_buttons(buttons_raw)
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer("<b>Предпросмотр рассылки</b>", parse_mode="HTML")
    await message.answer(preview_text, reply_markup=preview_markup, parse_mode="HTML", disable_web_page_preview=False)
    await message.answer(
        "Проверь текст и кнопки. Если все ок, запускай рассылку.",
        reply_markup=admin_broadcast_preview_keyboard(),
    )


def _broadcast_task_running() -> bool:
    return _broadcast_task is not None and not _broadcast_task.done()


async def _run_broadcast(*, bot, admin_id: int, text: str, reply_markup: InlineKeyboardMarkup | None) -> None:
    blocked_user_ids: list[int] = []
    delivered = 0
    failed = 0

    try:
        async with get_session() as session:
            user_ids = await list_known_user_ids(session)

        for index, user_id in enumerate(user_ids, start=1):
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                    disable_web_page_preview=False,
                )
                delivered += 1
            except TelegramForbiddenError:
                blocked_user_ids.append(user_id)
            except TelegramBadRequest as exc:
                error_text = str(exc).lower()
                if "chat not found" in error_text or "bot was blocked" in error_text:
                    blocked_user_ids.append(user_id)
                else:
                    failed += 1
            except Exception:
                failed += 1

            if index % 20 == 0:
                await asyncio.sleep(1.0)
            else:
                await asyncio.sleep(0.05)

        async with get_session() as session:
            await mark_users_blocked(session, blocked_user_ids)

        await bot.send_message(
            chat_id=admin_id,
            text=(
                "<b>Рассылка завершена</b>\n\n"
                f"Отправлено: <code>{delivered}</code>\n"
                f"Заблокировали бота: <code>{len(blocked_user_ids)}</code>\n"
                f"Ошибки отправки: <code>{failed}</code>"
            ),
            parse_mode="HTML",
        )
    except Exception as exc:
        await bot.send_message(
            chat_id=admin_id,
            text=(
                "<b>Рассылка завершилась с ошибкой</b>\n\n"
                f"<code>{html.escape(str(exc))}</code>"
            ),
            parse_mode="HTML",
        )


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
        f"Пользователи: <code>{audience['known_users']}</code>\n"
        f"Получатели рассылки: <code>{audience['broadcast_recipients']}</code>"
    )


@router.message(Command("admin"))
async def on_admin_command(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    await message.answer(await _build_panel_text(), reply_markup=admin_panel_keyboard(), parse_mode="HTML")


@router.message(Command("deliver"))
async def on_deliver_command(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /deliver <order_id>")
        return
    order_id = parts[1].strip()
    async with get_session() as session:
        order = await get_order(session, order_id)
    if order is None:
        await message.answer("Заказ не найден.")
        return
    await state.set_state(AdminDeliveryStates.waiting_for_delivery_text)
    await state.update_data(delivery_order_id=order.id)
    await message.answer(
        "Отправь следующим сообщением текст, который нужно доставить покупателю в бота.\n\n"
        f"Заказ: <code>{order.id}</code>\n"
        f"Покупатель: <code>{order.tg_user_id}</code>\n"
        f"Тариф: <b>{order.product_title}</b>",
        parse_mode="HTML",
    )


@router.message(AdminDeliveryStates.waiting_for_delivery_text)
async def on_delivery_text(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await state.clear()
        return
    payload = await state.get_data()
    order_id = str(payload.get("delivery_order_id") or "").strip()
    delivery_text = (message.text or "").strip()
    if not order_id or not delivery_text:
        await state.clear()
        await message.answer("Не удалось отправить выдачу.")
        return

    async with get_session() as session:
        order = await get_order(session, order_id)
        if order is None:
            await state.clear()
            await message.answer("Заказ не найден.")
            return
        order = await mark_order_delivered(session, order_id=order.id)
        if order is not None:
            await get_sheets_store().upsert_order(order)

    try:
        await message.bot.send_message(
            chat_id=order.tg_user_id,
            text=(
                "<b>Доступ по заказу готов</b>\n\n"
                f"Тариф: <b>{order.product_title}</b>\n"
                f"Заказ: <code>{order.id[:8]}</code>\n\n"
                f"{html.escape(delivery_text)}"
            ),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        await state.clear()
        await message.answer("Не удалось доставить сообщение пользователю.")
        return

    await state.clear()
    await message.answer("Выдача отправлена пользователю.")


@router.callback_query(F.data == "admin_panel")
async def on_admin_panel(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await _replace_admin_message(callback, await _build_panel_text(), admin_panel_keyboard())
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

    await _replace_admin_message(callback, "\n".join(lines), admin_back_keyboard())
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

    await _replace_admin_message(callback, "\n".join(lines), admin_back_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast")
async def on_admin_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.clear()
    await state.set_state(AdminBroadcastStates.waiting_for_text)
    await _replace_admin_message(
        callback,
        (
            "<b>Рассылка</b>\n\n"
            "Отправь следующим сообщением текст рассылки.\n"
            "Поддерживается обычное Telegram-форматирование: жирный, курсив, ссылки.\n\n"
            "После текста я запрошу inline-кнопки и покажу предпросмотр."
        ),
        admin_back_keyboard(),
    )
    await callback.answer()


@router.message(AdminBroadcastStates.waiting_for_text)
async def on_broadcast_text(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await state.clear()
        return
    text = _message_html(message)
    if not text:
        await message.answer("Текст рассылки пустой. Отправь текст еще раз.")
        return
    await state.update_data(broadcast_text=text)
    await state.set_state(AdminBroadcastStates.waiting_for_buttons)
    await message.answer(
        (
            "Теперь отправь inline-кнопки.\n\n"
            "Формат: <code>Текст | https://example.com</code>\n"
            "Каждая кнопка с новой строки, пустая строка разделяет ряды.\n\n"
            "Если кнопки не нужны, отправь <code>-</code>"
        ),
        parse_mode="HTML",
    )


@router.message(AdminBroadcastStates.waiting_for_buttons)
async def on_broadcast_buttons(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await state.clear()
        return
    raw = (message.text or "").strip()
    try:
        _parse_broadcast_buttons(raw)
    except ValueError as exc:
        await message.answer(f"{html.escape(str(exc))}\n\nПопробуй еще раз или отправь <code>-</code>.", parse_mode="HTML")
        return
    await state.update_data(broadcast_buttons_raw=raw)
    await _send_broadcast_preview(message, state)


@router.callback_query(F.data == "admin_broadcast_edit_text")
async def on_broadcast_edit_text(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.set_state(AdminBroadcastStates.waiting_for_text)
    await _replace_admin_message(callback, "Отправь новый текст рассылки.", admin_back_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast_edit_buttons")
async def on_broadcast_edit_buttons(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.set_state(AdminBroadcastStates.waiting_for_buttons)
    await _replace_admin_message(
        callback,
        (
            "Отправь новый набор inline-кнопок.\n\n"
            "Формат: <code>Текст | https://example.com</code>\n"
            "Пустая строка разделяет ряды.\n"
            "Если кнопки не нужны, отправь <code>-</code>"
        ),
        admin_back_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast_cancel")
async def on_broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.clear()
    await _replace_admin_message(callback, await _build_panel_text(), admin_panel_keyboard())
    await callback.answer("Рассылка отменена.")


@router.callback_query(F.data == "admin_broadcast_send")
async def on_broadcast_send(callback: CallbackQuery, state: FSMContext) -> None:
    global _broadcast_task

    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    if _broadcast_task_running():
        await callback.answer("Рассылка уже выполняется.", show_alert=True)
        return

    data = await state.get_data()
    text = str(data.get("broadcast_text") or "").strip()
    buttons_raw = str(data.get("broadcast_buttons_raw") or "")
    if not text:
        await state.clear()
        await callback.answer("Текст рассылки потерян. Начни заново.", show_alert=True)
        return
    try:
        reply_markup = _parse_broadcast_buttons(buttons_raw)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await state.clear()
    await _replace_admin_message(
        callback,
        "Рассылка запущена. После завершения пришлю сводку по отправке.",
        admin_panel_keyboard(),
    )
    await callback.answer()

    _broadcast_task = asyncio.create_task(
        _run_broadcast(
            bot=callback.bot,
            admin_id=callback.from_user.id,
            text=text,
            reply_markup=reply_markup,
        )
    )
