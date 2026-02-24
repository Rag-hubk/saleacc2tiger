from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from saleacc_bot.config import get_settings
from saleacc_bot.db import get_session
from saleacc_bot.keyboards import (
    admin_broadcast_add_button_keyboard,
    admin_broadcast_menu_keyboard,
    admin_broadcast_preview_keyboard,
    admin_broadcast_segment_keyboard,
    admin_paginated_keyboard,
    admin_panel_keyboard,
    admin_sales_keyboard,
    admin_stats_keyboard,
)
from saleacc_bot.models import Order, OrderStatus, PaymentMethod
from saleacc_bot.services.catalog import list_active_products
from saleacc_bot.services.inventory import get_inventory_summary_by_slug, get_stock_map, list_recent_sales
from saleacc_bot.services.orders import deliver_order_csv, get_order, mark_order_paid
from saleacc_bot.services.users import get_audience_stats, list_broadcast_user_ids, mark_users_blocked

router = Router(name="admin")
settings = get_settings()
_ADMIN_LIST_PAGE_SIZE = 10
_BROADCAST_DELAY_SECONDS = 0.07


@dataclass
class BroadcastDraft:
    segment: str | None = None
    source_chat_id: int | None = None
    source_message_id: int | None = None
    button_text: str | None = None
    button_url: str | None = None
    step: str = "idle"


_broadcast_drafts: dict[int, BroadcastDraft] = {}


def _is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


async def _safe_edit(callback: CallbackQuery, text: str, reply_markup) -> None:
    if callback.message is None:
        return
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise


def _has_broadcast_draft(message: Message) -> bool:
    user = message.from_user
    if user is None:
        return False
    return user.id in _broadcast_drafts


async def _load_admin_data() -> tuple[list, dict[int, int], dict[str, dict[str, int]], dict[str, int]]:
    async with get_session() as session:
        products = list(await list_active_products(session))
        stock_map = await get_stock_map(session, [p.id for p in products])
        summary_by_slug = await get_inventory_summary_by_slug([p.slug for p in products])
        audience = await get_audience_stats(session)
    return products, stock_map, summary_by_slug, audience


async def _build_admin_overview_text() -> str:
    products, stock_map, summary_by_slug, audience = await _load_admin_data()
    lines = [
        "Admin панель",
        "",
        "Выберите действие кнопками ниже.",
        "",
    ]
    if products:
        lines.append("Склад:")
        for product in products:
            info = summary_by_slug.get(product.slug, {})
            lines.append(
                f"- {product.title}: free={info.get('free', 0)} | reserved={info.get('reserved', 0)} | "
                f"sold={info.get('sold', 0)} | stock={stock_map.get(product.id, 0)}"
            )
    else:
        lines.append("Каталог пуст.")

    lines.extend(
        [
            "",
            "Аудитория:",
            f"- users={audience.get('known_users', 0)} | blocked={audience.get('blocked_users', 0)} | "
            f"broadcast={audience.get('broadcast_recipients', 0)}",
        ]
    )
    return "\n".join(lines)


async def _build_admin_stats_text() -> str:
    products, stock_map, summary_by_slug, audience = await _load_admin_data()
    lines = ["Статистика", ""]
    if not products:
        lines.append("Каталог пуст.")
    else:
        for product in products:
            info = summary_by_slug.get(product.slug, {})
            lines.append(
                f"{product.title}\n"
                f"free={info.get('free', 0)} | reserved={info.get('reserved', 0)} | "
                f"sold={info.get('sold', 0)} | total={info.get('total', 0)} | stock={stock_map.get(product.id, 0)}"
            )
            lines.append("")

    lines.extend(
        [
            "Аудитория:",
            f"known_users={audience.get('known_users', 0)}",
            f"blocked_users={audience.get('blocked_users', 0)}",
            f"broadcast_recipients={audience.get('broadcast_recipients', 0)}",
        ]
    )
    return "\n".join(lines)


async def _build_admin_sales_text(limit: int = 20) -> str:
    sales = await list_recent_sales(limit=limit)
    if not sales:
        return "Продажи\n\nПока нет продаж."

    lines = ["Продажи", ""]
    for row in sales:
        lines.append(
            f"{row.get('order_id', '-')[:8]} | {row.get('product', '-')} x{row.get('quantity', '-')} | "
            f"tg:{row.get('buyer_tg_id', '-')} | {row.get('sold_at', '-')[:19]}"
        )
    return "\n".join(lines)


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _normalize_page(raw: str | None) -> int:
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _format_user_label(user_id: int, username: str | None) -> str:
    if username:
        return f"@{username} ({user_id})"
    return str(user_id)


def _format_order_status(status: str) -> str:
    by_status = {
        "created": "создан",
        "pending_payment": "ожидает оплату",
        "paid": "оплачен",
        "delivered": "выдан",
        "cancelled": "отменен",
        "failed": "ошибка",
    }
    return by_status.get(status, status)


async def _load_paid_buyers() -> list[dict[str, object]]:
    async with get_session() as session:
        orders = list(
            await session.scalars(
                select(Order)
                .where(Order.status.in_([OrderStatus.PAID, OrderStatus.DELIVERED]))
                .order_by(Order.updated_at.desc())
            )
        )

    by_user: dict[int, dict[str, object]] = {}
    for order in orders:
        user_id = int(order.tg_user_id)
        current = by_user.get(user_id)
        if current is None:
            by_user[user_id] = {
                "tg_user_id": user_id,
                "tg_username": order.tg_username,
                "orders_count": 1,
                "total_spent_cents": int(order.total_price),
                "last_paid_at": order.updated_at or order.created_at,
            }
            continue

        current["orders_count"] = int(current["orders_count"]) + 1
        current["total_spent_cents"] = int(current["total_spent_cents"]) + int(order.total_price)
        if not current.get("tg_username") and order.tg_username:
            current["tg_username"] = order.tg_username

    entries = list(by_user.values())
    entries.sort(key=lambda row: row.get("last_paid_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return entries


async def _load_abandoned_buyers() -> list[dict[str, object]]:
    async with get_session() as session:
        orders = list(
            await session.scalars(
                select(Order)
                .where(
                    Order.payment_method == PaymentMethod.CRYPTO,
                    Order.status.in_([OrderStatus.CREATED, OrderStatus.PENDING_PAYMENT, OrderStatus.CANCELLED, OrderStatus.FAILED]),
                )
                .order_by(Order.updated_at.desc())
            )
        )

    by_user: dict[int, dict[str, object]] = {}
    for order in orders:
        user_id = int(order.tg_user_id)
        current = by_user.get(user_id)
        if current is None:
            by_user[user_id] = {
                "tg_user_id": user_id,
                "tg_username": order.tg_username,
                "attempts_count": 1,
                "active_holds": 1 if order.status in {OrderStatus.CREATED, OrderStatus.PENDING_PAYMENT} else 0,
                "cancelled_count": 1 if order.status == OrderStatus.CANCELLED else 0,
                "failed_count": 1 if order.status == OrderStatus.FAILED else 0,
                "last_status": order.status.value,
                "last_attempt_at": order.updated_at or order.created_at,
            }
            continue

        current["attempts_count"] = int(current["attempts_count"]) + 1
        if order.status in {OrderStatus.CREATED, OrderStatus.PENDING_PAYMENT}:
            current["active_holds"] = int(current["active_holds"]) + 1
        elif order.status == OrderStatus.CANCELLED:
            current["cancelled_count"] = int(current["cancelled_count"]) + 1
        elif order.status == OrderStatus.FAILED:
            current["failed_count"] = int(current["failed_count"]) + 1

        if not current.get("tg_username") and order.tg_username:
            current["tg_username"] = order.tg_username

    entries = list(by_user.values())
    entries.sort(key=lambda row: row.get("last_attempt_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return entries


def _slice_page(rows: list[dict[str, object]], page: int) -> tuple[list[dict[str, object]], int]:
    total_pages = max(1, math.ceil(len(rows) / _ADMIN_LIST_PAGE_SIZE))
    safe_page = min(max(0, page), total_pages - 1)
    start = safe_page * _ADMIN_LIST_PAGE_SIZE
    end = start + _ADMIN_LIST_PAGE_SIZE
    return rows[start:end], safe_page


def _buyers_text(*, rows: list[dict[str, object]], page: int, total_rows: int) -> str:
    lines = ["Покупатели", "", f"Всего уникальных покупателей: {total_rows}", ""]
    if not rows:
        lines.append("Пока нет оплаченных заказов.")
        return "\n".join(lines)

    for idx, row in enumerate(rows, start=page * _ADMIN_LIST_PAGE_SIZE + 1):
        user_label = _format_user_label(int(row["tg_user_id"]), row.get("tg_username"))  # type: ignore[arg-type]
        total_spent = int(row["total_spent_cents"]) / 100
        lines.append(f"{idx}. {user_label}")
        lines.append(
            f"   Заказов: {row['orders_count']} | Сумма: ${total_spent:.2f} | Последняя оплата: {_format_dt(row.get('last_paid_at'))}"  # type: ignore[arg-type]
        )
    return "\n".join(lines)


def _abandoned_text(*, rows: list[dict[str, object]], page: int, total_rows: int) -> str:
    lines = ["Неоплаченные попытки", "", f"Всего пользователей: {total_rows}", ""]
    if not rows:
        lines.append("Нет пользователей с незавершенной оплатой.")
        return "\n".join(lines)

    for idx, row in enumerate(rows, start=page * _ADMIN_LIST_PAGE_SIZE + 1):
        user_label = _format_user_label(int(row["tg_user_id"]), row.get("tg_username"))  # type: ignore[arg-type]
        lines.append(f"{idx}. {user_label}")
        lines.append(
            "   "
            f"Попыток: {row['attempts_count']} | Активных броней: {row['active_holds']} | "
            f"Отменено: {row['cancelled_count']} | Ошибок: {row['failed_count']} | "
            f"Последний статус: {_format_order_status(str(row['last_status']))} | "
            f"Последняя попытка: {_format_dt(row.get('last_attempt_at'))}"  # type: ignore[arg-type]
        )
    return "\n".join(lines)


def _clear_broadcast_draft(admin_id: int) -> None:
    _broadcast_drafts.pop(admin_id, None)


def _broadcast_segment_label(segment: str) -> str:
    if segment == "abandoned":
        return "Не оплатили"
    return "Все пользователи"


def _broadcast_button_markup(draft: BroadcastDraft) -> InlineKeyboardMarkup | None:
    if not draft.button_text or not draft.button_url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=draft.button_text, url=draft.button_url)],
        ]
    )


async def _resolve_broadcast_recipients(segment: str, admin_user_id: int) -> list[int]:
    async with get_session() as session:
        all_recipients = await list_broadcast_user_ids(session)
        if segment == "all":
            recipients = all_recipients
        elif segment == "abandoned":
            abandoned_ids = {
                int(value)
                for value in await session.scalars(
                    select(Order.tg_user_id)
                    .where(
                        Order.payment_method == PaymentMethod.CRYPTO,
                        Order.status.in_(
                            [
                                OrderStatus.CREATED,
                                OrderStatus.PENDING_PAYMENT,
                                OrderStatus.CANCELLED,
                                OrderStatus.FAILED,
                            ]
                        ),
                    )
                    .distinct()
                )
            }
            known = set(all_recipients)
            recipients = sorted(known.intersection(abandoned_ids))
        else:
            recipients = []

    return [uid for uid in recipients if uid != admin_user_id]


def _is_valid_broadcast_content(message: Message) -> bool:
    return bool(
        message.text
        or message.photo
        or message.video
        or message.document
        or message.animation
    )


def _parse_https_url(raw: str) -> str | None:
    candidate = raw.strip()
    if not candidate:
        return None
    if candidate.startswith("t.me/"):
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return candidate


async def _send_broadcast_preview(admin_message: Message, draft: BroadcastDraft) -> None:
    if draft.source_chat_id is None or draft.source_message_id is None or draft.segment is None:
        await admin_message.answer("Черновик рассылки неполный. Начните заново.")
        return

    recipients = await _resolve_broadcast_recipients(draft.segment, admin_message.from_user.id)
    await admin_message.answer("Предпросмотр сообщения:")
    await admin_message.bot.copy_message(
        chat_id=admin_message.chat.id,
        from_chat_id=draft.source_chat_id,
        message_id=draft.source_message_id,
        reply_markup=_broadcast_button_markup(draft),
    )
    await admin_message.answer(
        "Параметры рассылки:\n"
        f"- Сегмент: {_broadcast_segment_label(draft.segment)}\n"
        f"- Получателей: {len(recipients)}\n"
        f"- Inline кнопка: {'да' if draft.button_text and draft.button_url else 'нет'}\n"
        f"- Пауза между сообщениями: {_BROADCAST_DELAY_SECONDS:.2f} сек",
        reply_markup=admin_broadcast_preview_keyboard(),
    )
    draft.step = "ready_to_send"


async def _run_broadcast(
    *,
    admin_message: Message,
    segment: str,
    source_chat_id: int | None,
    source_message_id: int | None,
    text_payload: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> tuple[int, int, int, int]:
    recipients = await _resolve_broadcast_recipients(segment, admin_message.from_user.id)
    if not recipients:
        return 0, 0, 0, 0

    await admin_message.answer(f"Рассылка запущена. Получателей: {len(recipients)}")

    sent = 0
    failed = 0
    blocked: list[int] = []

    for tg_user_id in recipients:
        try:
            if source_chat_id is not None and source_message_id is not None:
                await admin_message.bot.copy_message(
                    chat_id=tg_user_id,
                    from_chat_id=source_chat_id,
                    message_id=source_message_id,
                    reply_markup=reply_markup,
                )
            else:
                await admin_message.bot.send_message(
                    chat_id=tg_user_id,
                    text=text_payload or "",
                    reply_markup=reply_markup,
                )
            sent += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            try:
                if source_chat_id is not None and source_message_id is not None:
                    await admin_message.bot.copy_message(
                        chat_id=tg_user_id,
                        from_chat_id=source_chat_id,
                        message_id=source_message_id,
                        reply_markup=reply_markup,
                    )
                else:
                    await admin_message.bot.send_message(
                        chat_id=tg_user_id,
                        text=text_payload or "",
                        reply_markup=reply_markup,
                    )
                sent += 1
            except TelegramForbiddenError:
                blocked.append(tg_user_id)
            except TelegramAPIError:
                failed += 1
        except TelegramForbiddenError:
            blocked.append(tg_user_id)
        except TelegramAPIError:
            failed += 1

        await asyncio.sleep(_BROADCAST_DELAY_SECONDS)

    if blocked:
        async with get_session() as session:
            await mark_users_blocked(session, blocked)

    return len(recipients), sent, failed, len(blocked)


@router.message(Command("admin"))
async def admin_panel(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    _clear_broadcast_draft(message.from_user.id)
    await message.answer(await _build_admin_overview_text(), reply_markup=admin_panel_keyboard())


@router.callback_query(F.data == "admin_panel")
async def admin_panel_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    _clear_broadcast_draft(callback.from_user.id)
    await _safe_edit(callback, await _build_admin_overview_text(), admin_panel_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin_stats")
async def admin_stats_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await _safe_edit(callback, await _build_admin_stats_text(), admin_stats_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin_sales")
async def admin_sales_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await _safe_edit(callback, await _build_admin_sales_text(limit=20), admin_sales_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("admin_buyers:"))
async def admin_buyers_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    _, _, raw_page = callback.data.partition(":")
    page = _normalize_page(raw_page)
    buyers = await _load_paid_buyers()
    page_rows, safe_page = _slice_page(buyers, page)
    total_pages = max(1, math.ceil(len(buyers) / _ADMIN_LIST_PAGE_SIZE))
    await _safe_edit(
        callback,
        _buyers_text(rows=page_rows, page=safe_page, total_rows=len(buyers)),
        admin_paginated_keyboard(prefix="admin_buyers", page=safe_page, total_pages=total_pages),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_abandoned:"))
async def admin_abandoned_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    _, _, raw_page = callback.data.partition(":")
    page = _normalize_page(raw_page)
    abandoned = await _load_abandoned_buyers()
    page_rows, safe_page = _slice_page(abandoned, page)
    total_pages = max(1, math.ceil(len(abandoned) / _ADMIN_LIST_PAGE_SIZE))
    await _safe_edit(
        callback,
        _abandoned_text(rows=page_rows, page=safe_page, total_rows=len(abandoned)),
        admin_paginated_keyboard(prefix="admin_abandoned", page=safe_page, total_pages=total_pages),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast_menu")
async def admin_broadcast_menu_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    _clear_broadcast_draft(callback.from_user.id)
    await _safe_edit(
        callback,
        "Рассылка\n\n"
        "Создайте новую рассылку и выберите сегмент аудитории.\n"
        "Перед отправкой бот покажет предпросмотр.",
        admin_broadcast_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast_start")
async def admin_broadcast_start_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    _broadcast_drafts[callback.from_user.id] = BroadcastDraft(step="await_segment")
    await _safe_edit(
        callback,
        "Рассылка\n\n"
        "Шаг 1/4: выберите сегмент получателей.",
        admin_broadcast_segment_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_broadcast_segment:"))
async def admin_broadcast_segment_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    _, _, segment = callback.data.partition(":")
    if segment not in {"all", "abandoned"}:
        await callback.answer("Некорректный сегмент", show_alert=True)
        return

    draft = _broadcast_drafts.get(callback.from_user.id)
    if draft is None:
        draft = BroadcastDraft()
        _broadcast_drafts[callback.from_user.id] = draft

    draft.segment = segment
    draft.source_chat_id = None
    draft.source_message_id = None
    draft.button_text = None
    draft.button_url = None
    draft.step = "await_content"
    await _safe_edit(
        callback,
        "Рассылка\n\n"
        f"Сегмент: {_broadcast_segment_label(segment)}\n\n"
        "Шаг 2/4: отправьте контент для рассылки.\n"
        "Поддерживается: текст, фото, видео, документ, GIF.",
        admin_broadcast_segment_keyboard(),
    )
    await callback.answer("Сегмент выбран")


@router.callback_query(F.data.startswith("admin_broadcast_button:"))
async def admin_broadcast_button_choice_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    _, _, choice = callback.data.partition(":")
    draft = _broadcast_drafts.get(callback.from_user.id)
    if draft is None or draft.step != "await_button_choice":
        await callback.answer("Сначала отправьте контент", show_alert=True)
        return

    if choice == "no":
        draft.button_text = None
        draft.button_url = None
        if callback.message is not None:
            await _send_broadcast_preview(callback.message, draft)
        await callback.answer()
        return

    if choice != "yes":
        await callback.answer("Некорректный выбор", show_alert=True)
        return

    draft.step = "await_button_text"
    await _safe_edit(
        callback,
        "Рассылка\n\n"
        "Шаг 3/4: отправьте текст для Inline кнопки.\n"
        "Пример: Купить сейчас",
        admin_broadcast_add_button_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast_send")
async def admin_broadcast_send_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    draft = _broadcast_drafts.get(callback.from_user.id)
    if draft is None or draft.step != "ready_to_send":
        await callback.answer("Нет готовой рассылки", show_alert=True)
        return
    if draft.segment is None:
        await callback.answer("Сегмент не выбран", show_alert=True)
        return
    if callback.message is None:
        await callback.answer("Сообщение недоступно", show_alert=True)
        return

    total, sent, failed, blocked = await _run_broadcast(
        admin_message=callback.message,
        segment=draft.segment,
        source_chat_id=draft.source_chat_id,
        source_message_id=draft.source_message_id,
        reply_markup=_broadcast_button_markup(draft),
    )
    _clear_broadcast_draft(callback.from_user.id)

    if total == 0:
        await _safe_edit(
            callback,
            "Рассылка\n\nНет получателей для выбранного сегмента.",
            admin_broadcast_menu_keyboard(),
        )
        await callback.answer("Нет получателей")
        return

    await _safe_edit(
        callback,
        "Рассылка завершена.\n"
        f"- Получателей: {total}\n"
        f"- Отправлено: {sent}\n"
        f"- Ошибок: {failed}\n"
        f"- Заблокировали бота: {blocked}",
        admin_broadcast_menu_keyboard(),
    )
    await callback.answer("Отправлено")


@router.callback_query(F.data == "admin_broadcast_cancel")
async def admin_broadcast_cancel_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    _clear_broadcast_draft(callback.from_user.id)
    await _safe_edit(
        callback,
        "Рассылка отменена.",
        admin_broadcast_menu_keyboard(),
    )
    await callback.answer("Отменено")


@router.message(Command("stock"))
async def admin_stock(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    await message.answer(await _build_admin_stats_text())


@router.message(Command("sales"))
async def admin_sales(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    await message.answer(await _build_admin_sales_text(limit=20))


@router.message(Command("mark_paid"))
async def admin_mark_paid(message: Message, command: CommandObject) -> None:
    if not _is_admin(message.from_user.id):
        return

    if not command.args:
        await message.answer("Использование: /mark_paid <order_id>")
        return

    order_id = command.args.strip()
    async with get_session() as session:
        order = await get_order(session, order_id)
        if order is None:
            await message.answer("Заказ не найден")
            return

        paid = await mark_order_paid(
            session,
            order_id=order.id,
            provider_charge_id="tribute-manual",
            telegram_payment_charge_id=None,
        )
        if paid is None:
            await message.answer("Статус заказа не позволяет подтвердить оплату")
            return

        csv_path = await deliver_order_csv(
            session,
            order_id=order.id,
            export_dir=settings.export_dir,
        )

    if csv_path is None:
        await message.answer("Оплата подтверждена, но не удалось сформировать выдачу")
        return

    await message.answer_document(
        FSInputFile(path=str(csv_path)),
        caption=f"Заказ {order_id[:8]} переведен в paid и выдан.",
    )


@router.message(Command("broadcast"))
async def admin_broadcast(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return

    _clear_broadcast_draft(message.from_user.id)
    await message.answer(
        "Рассылка\n\n"
        "Откройте мастер и соберите сообщение по шагам.\n"
        "Перед отправкой будет предпросмотр.",
        reply_markup=admin_broadcast_menu_keyboard(),
    )


@router.message(F.from_user.id.in_(settings.admin_ids), _has_broadcast_draft)
async def admin_broadcast_payload(message: Message) -> None:
    if message.from_user is None:
        return
    draft = _broadcast_drafts.get(message.from_user.id)
    if draft is None:
        return
    if message.text and message.text.startswith("/"):
        return

    if draft.step == "await_content":
        if not _is_valid_broadcast_content(message):
            await message.answer(
                "Неподдерживаемый тип контента.\n"
                "Отправьте текст, фото, видео, документ или GIF."
            )
            return
        draft.source_chat_id = message.chat.id
        draft.source_message_id = message.message_id
        draft.step = "await_button_choice"
        await message.answer(
            "Шаг 3/4: нужна Inline кнопка в рассылке?",
            reply_markup=admin_broadcast_add_button_keyboard(),
        )
        return

    if draft.step == "await_button_text":
        text = (message.text or "").strip()
        if not text:
            await message.answer("Отправьте текст кнопки обычным сообщением.")
            return
        if len(text) > 64:
            await message.answer("Текст кнопки слишком длинный. Максимум 64 символа.")
            return
        draft.button_text = text
        draft.step = "await_button_url"
        await message.answer("Шаг 4/4: отправьте URL кнопки. Формат: https://example.com")
        return

    if draft.step == "await_button_url":
        raw_url = (message.text or "").strip()
        parsed_url = _parse_https_url(raw_url)
        if not parsed_url:
            await message.answer("URL некорректный. Нужен полный адрес вида https://...")
            return
        draft.button_url = parsed_url
        await _send_broadcast_preview(message, draft)
        return

    if draft.step == "await_segment":
        await message.answer("Сначала выберите сегмент кнопками.")
        return

    if draft.step == "await_button_choice":
        await message.answer("Выберите вариант кнопками: добавить Inline кнопку или без кнопки.")
        return

    if draft.step == "ready_to_send":
        await message.answer("Черновик готов. Нажмите «Отправить» или «Отмена» в меню предпросмотра.")
