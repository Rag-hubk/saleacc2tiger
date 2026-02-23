from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, FSInputFile, Message

from saleacc_bot.config import get_settings
from saleacc_bot.db import get_session
from saleacc_bot.keyboards import (
    admin_broadcast_keyboard,
    admin_panel_keyboard,
    admin_sales_keyboard,
    admin_stats_keyboard,
)
from saleacc_bot.services.catalog import list_active_products
from saleacc_bot.services.inventory import get_inventory_summary_by_slug, get_stock_map, list_recent_sales
from saleacc_bot.services.orders import deliver_order_csv, get_order, mark_order_paid
from saleacc_bot.services.users import get_audience_stats, list_broadcast_user_ids, mark_users_blocked

router = Router(name="admin")
settings = get_settings()
_broadcast_waiting: set[int] = set()


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


async def _run_broadcast(
    *,
    admin_message: Message,
    source_message: Message | None,
    text_payload: str | None,
) -> tuple[int, int, int, int]:
    async with get_session() as session:
        recipients = await list_broadcast_user_ids(session)

    recipients = [uid for uid in recipients if uid != admin_message.from_user.id]
    if not recipients:
        return 0, 0, 0, 0

    await admin_message.answer(f"Рассылка запущена. Получателей: {len(recipients)}")

    sent = 0
    failed = 0
    blocked: list[int] = []

    for tg_user_id in recipients:
        try:
            if source_message is not None:
                await admin_message.bot.copy_message(
                    chat_id=tg_user_id,
                    from_chat_id=source_message.chat.id,
                    message_id=source_message.message_id,
                )
            else:
                await admin_message.bot.send_message(chat_id=tg_user_id, text=text_payload or "")
            sent += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            try:
                if source_message is not None:
                    await admin_message.bot.copy_message(
                        chat_id=tg_user_id,
                        from_chat_id=source_message.chat.id,
                        message_id=source_message.message_id,
                    )
                else:
                    await admin_message.bot.send_message(chat_id=tg_user_id, text=text_payload or "")
                sent += 1
            except TelegramForbiddenError:
                blocked.append(tg_user_id)
            except TelegramAPIError:
                failed += 1
        except TelegramForbiddenError:
            blocked.append(tg_user_id)
        except TelegramAPIError:
            failed += 1

        await asyncio.sleep(0.03)

    if blocked:
        async with get_session() as session:
            await mark_users_blocked(session, blocked)

    return len(recipients), sent, failed, len(blocked)


@router.message(Command("admin"))
async def admin_panel(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    _broadcast_waiting.discard(message.from_user.id)
    await message.answer(await _build_admin_overview_text(), reply_markup=admin_panel_keyboard())


@router.callback_query(F.data == "admin_panel")
async def admin_panel_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    _broadcast_waiting.discard(callback.from_user.id)
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


@router.callback_query(F.data == "admin_broadcast_menu")
async def admin_broadcast_menu_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    _broadcast_waiting.add(callback.from_user.id)
    await _safe_edit(
        callback,
        "Рассылка\n\n"
        "Отправьте следующим сообщением текст, фото, видео или документ.\n"
        "Это сообщение будет разослано всем пользователям.\n\n"
        "Для отмены нажмите кнопку ниже.",
        admin_broadcast_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast_cancel")
async def admin_broadcast_cancel_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    _broadcast_waiting.discard(callback.from_user.id)
    await _safe_edit(callback, await _build_admin_overview_text(), admin_panel_keyboard())
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
async def admin_broadcast(message: Message, command: CommandObject) -> None:
    if not _is_admin(message.from_user.id):
        return

    text_payload = (command.args or "").strip()
    source_message = message.reply_to_message
    if not text_payload and source_message is None:
        _broadcast_waiting.add(message.from_user.id)
        await message.answer(
            "Режим рассылки включен.\n"
            "Отправьте следующим сообщением текст, фото, видео или документ.",
            reply_markup=admin_broadcast_keyboard(),
        )
        return

    total, sent, failed, blocked = await _run_broadcast(
        admin_message=message,
        source_message=source_message,
        text_payload=text_payload or None,
    )
    if total == 0:
        await message.answer("Нет получателей для рассылки.")
        return
    await message.answer(
        "Рассылка завершена.\n"
        f"- Получателей: {total}\n"
        f"- Отправлено: {sent}\n"
        f"- Ошибок: {failed}\n"
        f"- Заблокировали бота: {blocked}"
    )


@router.message(F.from_user.id.in_(settings.admin_ids), ~F.text.startswith("/"))
async def admin_broadcast_payload(message: Message) -> None:
    if message.from_user is None:
        return
    if message.from_user.id not in _broadcast_waiting:
        return

    _broadcast_waiting.discard(message.from_user.id)
    total, sent, failed, blocked = await _run_broadcast(
        admin_message=message,
        source_message=message,
        text_payload=None,
    )
    if total == 0:
        await message.answer("Нет получателей для рассылки.")
        await message.answer(await _build_admin_overview_text(), reply_markup=admin_panel_keyboard())
        return

    await message.answer(
        "Рассылка завершена.\n"
        f"- Получателей: {total}\n"
        f"- Отправлено: {sent}\n"
        f"- Ошибок: {failed}\n"
        f"- Заблокировали бота: {blocked}"
    )
    await message.answer(await _build_admin_overview_text(), reply_markup=admin_panel_keyboard())
