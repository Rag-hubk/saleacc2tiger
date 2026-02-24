from __future__ import annotations

import asyncio
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, FSInputFile, Message

from saleacc_bot.config import get_settings
from saleacc_bot.db import get_session
from saleacc_bot.keyboards import (
    catalog_keyboard,
    cryptobot_checkout_keyboard,
    group_details_keyboard,
    orders_keyboard,
    payment_methods_keyboard,
    quantity_selector_keyboard,
    tribute_checkout_keyboard,
)
from saleacc_bot.models import OrderStatus, PaymentMethod
from saleacc_bot.services.catalog import get_product_by_id, list_active_products
from saleacc_bot.services.cryptobot import CryptoBotClient
from saleacc_bot.services.inventory import get_stock_map
from saleacc_bot.services.orders import (
    RESERVE_MINUTES,
    build_tribute_url_for_product,
    cancel_pending_order,
    cleanup_expired_reservations,
    create_order_with_reservation,
    deliver_order_csv,
    get_order,
    list_user_orders,
    mark_order_paid,
    resolve_tribute_base_url,
)
from saleacc_bot.services.users import touch_user
from saleacc_bot.ui import is_admin, main_menu_payload

router = Router(name="user")
settings = get_settings()
crypto_client = CryptoBotClient(settings)
_main_menu_message_id: dict[int, int] = {}
_checkout_timeout_tasks: dict[str, asyncio.Task] = {}
GROUP_ORDER = ("gpt-pro", "lovable", "replit")


def _effective_unit_price_cents(product, method: str) -> int:
    if (
        settings.payment_test_enabled
        and product.slug == settings.payment_test_product_slug
    ):
        if method == "crypto":
            return max(1, settings.payment_test_crypto_price_cents)
        if method == "fiat":
            return max(1, settings.payment_test_fiat_price_cents)
    return product.price_usd_cents


def _is_test_mode_available(user_id: int) -> bool:
    if not settings.test_mode_enabled:
        return False
    if settings.test_mode_admin_only and not is_admin(settings, user_id):
        return False
    return True


def _is_crypto_available() -> bool:
    return settings.cryptobot_enabled


def _is_fiat_available_for_product(product_slug: str) -> bool:
    if not settings.tribute_enabled:
        return False
    return (
        resolve_tribute_base_url(
            product_slug=product_slug,
            fallback_base_url=settings.tribute_base_url,
            tribute_link_gpt_pro_1m=settings.tribute_link_gpt_pro_1m,
            tribute_link_gpt_pro_3m=settings.tribute_link_gpt_pro_3m,
            tribute_link_lovable_100=settings.tribute_link_lovable_100,
            tribute_link_lovable_200=settings.tribute_link_lovable_200,
            tribute_link_lovable_300=settings.tribute_link_lovable_300,
            tribute_link_replit_core=settings.tribute_link_replit_core,
            tribute_link_replit_team=settings.tribute_link_replit_team,
        )
        is not None
    )


async def _safe_delete_user_message(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


async def _safe_edit(callback: CallbackQuery, text: str, reply_markup) -> None:
    if callback.message is None:
        return
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise


def _schedule_checkout_timeout(
    *,
    bot: Bot,
    order_id: str,
    chat_id: int,
    message_id: int,
    user_id: int,
) -> None:
    existing = _checkout_timeout_tasks.get(order_id)
    if existing and not existing.done():
        existing.cancel()

    task = asyncio.create_task(
        _checkout_timeout_job(
            bot=bot,
            order_id=order_id,
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
        )
    )
    _checkout_timeout_tasks[order_id] = task


async def _checkout_timeout_job(
    *,
    bot: Bot,
    order_id: str,
    chat_id: int,
    message_id: int,
    user_id: int,
) -> None:
    try:
        await asyncio.sleep((RESERVE_MINUTES * 60) + 5)

        async with get_session() as session:
            await cleanup_expired_reservations(session)
            order = await get_order(session, order_id)
            if order is None or order.status != OrderStatus.CANCELLED:
                return

        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except (TelegramBadRequest, TelegramForbiddenError):
            pass

        main_text, main_kb = main_menu_payload(settings, user_id)
        sent = await bot.send_message(
            chat_id=chat_id,
            text=main_text,
            reply_markup=main_kb,
            parse_mode="HTML",
        )
        _main_menu_message_id[user_id] = sent.message_id
    except asyncio.CancelledError:
        raise
    except Exception:
        return
    finally:
        _checkout_timeout_tasks.pop(order_id, None)


async def _load_catalog() -> tuple[list, dict[int, int]]:
    async with get_session() as session:
        products = list(await list_active_products(session))
        stock_map = await get_stock_map(session, [p.id for p in products])
        return products, stock_map


def _catalog_text(products: list, stock_map: dict[int, int]) -> str:
    if not products:
        return "<b>Каталог временно пуст.</b>"

    def group_slug(slug: str) -> str:
        if slug.startswith("gpt-pro"):
            return "gpt-pro"
        if slug.startswith("lovable"):
            return "lovable"
        if slug.startswith("replit"):
            return "replit"
        return slug

    grouped: dict[str, list] = {key: [] for key in GROUP_ORDER}
    for product in products:
        grouped.setdefault(group_slug(product.slug), []).append(product)

    lines = ["<b>Доступные подписки</b>", ""]
    title_map = {
        "gpt-pro": "GPT Pro",
        "lovable": "Lovable AI Pro",
        "replit": "Replit",
    }
    for key in GROUP_ORDER:
        items = grouped.get(key, [])
        if not items:
            continue
        total_stock = sum(stock_map.get(item.id, 0) for item in items)
        min_price = min(item.price_usd_cents for item in items) / 100
        lines.append(f"<b>{title_map[key]}</b> · от <code>${min_price:.0f}</code>")
        lines.append(f"В наличии: <b>{total_stock}</b>")
        lines.append("")
    lines.append("<i>Нажмите на сервис, чтобы выбрать подходящий вариант.</i>")
    lines.append("<blockquote>Оплата возможна в любой валюте, включая рубли.</blockquote>")
    return "\n".join(lines)


def _group_slug(product_slug: str) -> str:
    if product_slug.startswith("gpt-pro"):
        return "gpt-pro"
    if product_slug.startswith("lovable"):
        return "lovable"
    if product_slug.startswith("replit"):
        return "replit"
    return product_slug


def _variant_label(product_slug: str) -> str:
    if product_slug == "gpt-pro-1m":
        return "1 месяц"
    if product_slug == "gpt-pro-3m":
        return "3 месяца"
    if product_slug == "lovable-100":
        return "100 токенов"
    if product_slug == "lovable-200":
        return "200 токенов"
    if product_slug == "lovable-300":
        return "300 токенов"
    if product_slug == "replit-core":
        return "Core"
    if product_slug == "replit-team":
        return "Team"
    return "Тариф"


def _group_details_text(group: str, products: list, stock_map: dict[int, int]) -> str:
    by_slug = {p.slug: p for p in products}
    if group == "gpt-pro":
        one = by_slug.get("gpt-pro-1m")
        three = by_slug.get("gpt-pro-3m")
        return (
            "<b>GPT Pro</b>\n"
            "<blockquote>Подходит для активной работы с ChatGPT: доступ к <b>Codex 5.3</b>, GPT Pro и повышенным лимитам.</blockquote>\n"
            "Реальная цена по рынку за GPT Pro: <code>$200/мес</code>.\n\n"
            f"1 месяц: <code>${(one.price_usd_cents / 100):.0f}</code> · В наличии: <b>{stock_map.get(one.id, 0) if one else 0}</b>\n"
            f"3 месяца: <code>${(three.price_usd_cents / 100):.0f}</code> · В наличии: <b>{stock_map.get(three.id, 0) if three else 0}</b>"
        )
    if group == "lovable":
        l100 = by_slug.get("lovable-100")
        l200 = by_slug.get("lovable-200")
        l300 = by_slug.get("lovable-300")
        return (
            "<b>Lovable AI Pro</b>\n"
            "<blockquote>Для быстрого создания MVP и веб-приложений с помощью ИИ.</blockquote>\n"
            f"100 токенов на аккаунте: <code>${(l100.price_usd_cents / 100):.0f}</code> · В наличии: <b>{stock_map.get(l100.id, 0) if l100 else 0}</b>\n"
            f"200 токенов на аккаунте: <code>${(l200.price_usd_cents / 100):.0f}</code> · В наличии: <b>{stock_map.get(l200.id, 0) if l200 else 0}</b>\n"
            f"300 токенов на аккаунте: <code>${(l300.price_usd_cents / 100):.0f}</code> · В наличии: <b>{stock_map.get(l300.id, 0) if l300 else 0}</b>"
        )
    if group == "replit":
        core = by_slug.get("replit-core")
        team = by_slug.get("replit-team")
        return (
            "<b>Replit</b>\n"
            "<blockquote>Облачная среда разработки: AI-модели, деплой и хостинг проектов.</blockquote>\n"
            f"Core: <code>${(core.price_usd_cents / 100):.0f}</code> · В наличии: <b>{stock_map.get(core.id, 0) if core else 0}</b> · "
            "внутренний баланс <code>50 + 10 бонус</code>\n"
            f"Team: <code>${(team.price_usd_cents / 100):.0f}</code> · В наличии: <b>{stock_map.get(team.id, 0) if team else 0}</b> · "
            "внутренний баланс <code>120</code>"
        )

    return "<b>Раздел недоступен.</b>"


def _group_variants(group: str, products: list, stock_map: dict[int, int]) -> list[tuple[int, str, int, int]]:
    order_map = {
        "gpt-pro-1m": 1,
        "gpt-pro-3m": 2,
        "lovable-100": 1,
        "lovable-200": 2,
        "lovable-300": 3,
        "replit-core": 1,
        "replit-team": 2,
    }
    filtered = [p for p in products if _group_slug(p.slug) == group]
    ordered = sorted(filtered, key=lambda p: (order_map.get(p.slug, 999), p.id))
    return [(p.id, _variant_label(p.slug), p.price_usd_cents, stock_map.get(p.id, 0)) for p in ordered]


def _normalize_payment_method(method: str) -> str | None:
    normalized = method.strip().lower()
    if normalized in {"crypto", "fiat", "test", "pick"}:
        return normalized
    return None


def _payment_method_label(method: str) -> str:
    if method == "crypto":
        return "Криптой"
    if method == "fiat":
        return "Фиат"
    if method == "test":
        return "Тестовый режим"
    if method == "pick":
        return "не выбран"
    return method


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


def _format_order_total(order) -> str:
    amount_usd = order.total_price / 100
    if order.payment_method == PaymentMethod.CRYPTO:
        return f"<code>${amount_usd:.2f}</code> (эквивалент в крипте)"
    return f"<code>${amount_usd:.2f}</code>"


def _quantity_screen_text(product, stock: int, qty: int, method: str) -> str:
    unit_price = _effective_unit_price_cents(product, method) if method in {"crypto", "fiat"} else product.price_usd_cents
    lines = [
        "<b>Выбор количества</b>",
        "",
        f"Товар: <b>{escape(product.title)}</b>",
        f"Способ оплаты: <b>{_payment_method_label(method)}</b>",
        f"В наличии: <code>{stock}</code>",
        f"Выбрано: <code>{qty}</code>",
        f"Итого: <code>${((unit_price * qty) / 100):.2f}</code>",
    ]
    if method == "crypto":
        lines.append(f"Крипто-инвойс будет выставлен в <code>{escape(settings.cryptobot_asset)}</code>.")
    lines.append("")
    if method == "pick":
        lines.append("<i>Выберите количество и нажмите «Продолжить к оплате».</i>")
        lines.append("<i>Фиат доступен только для 1 шт за один заказ. Для 2+ используйте крипто.</i>")
    else:
        lines.append("<i>Используйте кнопки +/- и нажмите «Продолжить».</i>")
    return "\n".join(lines)


@router.message(CommandStart())
async def on_start(message: Message) -> None:
    async with get_session() as session:
        await touch_user(
            session,
            tg_user_id=message.from_user.id,
            tg_username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )

    prev_menu_id = _main_menu_message_id.get(message.from_user.id)
    if prev_menu_id:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=prev_menu_id)
        except TelegramBadRequest:
            pass

    main_text, main_kb = main_menu_payload(settings, message.from_user.id)
    sent = await message.answer(main_text, reply_markup=main_kb, parse_mode="HTML")
    _main_menu_message_id[message.from_user.id] = sent.message_id


@router.callback_query(F.data == "main")
async def on_main(callback: CallbackQuery) -> None:
    await _safe_edit(callback, *main_menu_payload(settings, callback.from_user.id))
    if callback.message:
        _main_menu_message_id[callback.from_user.id] = callback.message.message_id
    await callback.answer()


@router.callback_query(F.data == "catalog")
async def on_catalog_callback(callback: CallbackQuery) -> None:
    products, stock_map = await _load_catalog()
    await _safe_edit(
        callback,
        _catalog_text(products, stock_map),
        catalog_keyboard(products, stock_map),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("group:"))
async def on_group(callback: CallbackQuery) -> None:
    _, _, group = callback.data.partition(":")
    await _show_group_details(callback, group)
    await callback.answer()


@router.callback_query(F.data == "orders")
async def on_orders(callback: CallbackQuery) -> None:
    async with get_session() as session:
        orders = await list_user_orders(session, user_id=callback.from_user.id, limit=10)

    if not orders:
        text = "<b>Последние заказы</b>\n\n<i>Заказов пока нет.</i>"
    else:
        lines = ["<b>Последние заказы</b>", ""]
        for order in orders:
            title = order.product.title if order.product else "Товар"
            lines.append(
                f"<code>{escape(order.id[:8])}</code> | <b>{escape(title)}</b> x<code>{order.quantity}</code>"
            )
            lines.append(
                f"{escape(_format_order_status(order.status.value))} | "
                f"{escape(_payment_method_label(order.payment_method.value))} | "
                f"{_format_order_total(order)}"
            )
            lines.append("")
        text = "\n".join(lines)

    await _safe_edit(callback, text, orders_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("prod:"))
async def on_product(callback: CallbackQuery) -> None:
    _, _, raw_id = callback.data.partition(":")
    try:
        product_id = int(raw_id)
    except ValueError:
        await callback.answer("Некорректный товар", show_alert=True)
        return

    async with get_session() as session:
        product = await get_product_by_id(session, product_id)
    if product is None:
        await callback.answer("Товар недоступен", show_alert=True)
        return
    await _show_group_details(callback, _group_slug(product.slug))
    await callback.answer()


async def _show_group_details(callback: CallbackQuery, group: str) -> None:
    products, stock_map = await _load_catalog()
    variants = _group_variants(group, products, stock_map)
    if not variants:
        await callback.answer("Раздел недоступен", show_alert=True)
        return
    await _safe_edit(
        callback,
        _group_details_text(group, products, stock_map),
        group_details_keyboard(variants),
    )


async def _show_quantity_selector(callback: CallbackQuery, product_id: int, *, qty: int = 1) -> None:
    async with get_session() as session:
        product = await get_product_by_id(session, product_id)
        stock_map = await get_stock_map(session, [product_id])

    if product is None or not product.is_active:
        await callback.answer("Товар недоступен", show_alert=True)
        return

    stock = stock_map.get(product_id, 0)
    if stock < 1:
        await callback.answer("Недостаточно в наличии", show_alert=True)
        return

    normalized_qty = max(1, min(qty, stock))
    await _safe_edit(
        callback,
        _quantity_screen_text(product, stock, normalized_qty, "pick"),
        quantity_selector_keyboard(
            product_id,
            "pick",
            normalized_qty,
            min_qty=1,
            max_qty=stock,
        ),
    )


@router.callback_query(F.data == "noop")
async def on_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("buy:"))
async def on_buy(callback: CallbackQuery) -> None:
    try:
        parts = callback.data.split(":")
        raw_product_id = parts[1]
        product_id = int(raw_product_id)
        qty = int(parts[2]) if len(parts) > 2 else 1
    except (TypeError, ValueError, IndexError):
        await callback.answer("Некорректные параметры", show_alert=True)
        return

    await _show_quantity_selector(callback, product_id, qty=qty)
    await callback.answer()


@router.callback_query(F.data.startswith("paymethod:"))
async def on_pay_method(callback: CallbackQuery) -> None:
    try:
        parts = callback.data.split(":")
        raw_product_id = parts[1]
        raw_method = parts[2]
        product_id = int(raw_product_id)
        qty = int(parts[3]) if len(parts) > 3 else 1
    except (TypeError, ValueError, IndexError):
        await callback.answer("Некорректные параметры", show_alert=True)
        return

    method = _normalize_payment_method(raw_method)
    if method is None:
        await callback.answer("Некорректный способ оплаты", show_alert=True)
        return
    if method == "fiat" and qty != 1:
        await callback.answer("Фиат: доступна покупка только 1 шт.", show_alert=True)
        await _show_quantity_selector(callback, product_id, qty=1)
        return
    if method == "crypto" and not _is_crypto_available():
        await callback.answer("Крипто-оплата временно недоступна", show_alert=True)
        return
    if method == "test" and not _is_test_mode_available(callback.from_user.id):
        await callback.answer("Тестовый режим отключен", show_alert=True)
        return

    await _start_checkout(callback, product_id, method, qty)


@router.callback_query(F.data.startswith("qtyset:"))
async def on_qty_set(callback: CallbackQuery) -> None:
    try:
        _, raw_product_id, raw_method, raw_qty = callback.data.split(":", maxsplit=3)
        product_id = int(raw_product_id)
        qty = int(raw_qty)
    except (TypeError, ValueError):
        await callback.answer("Некорректные параметры", show_alert=True)
        return

    method = _normalize_payment_method(raw_method)
    if method is None:
        await callback.answer("Некорректный способ оплаты", show_alert=True)
        return

    if method == "crypto" and not _is_crypto_available():
        await callback.answer("Крипто-оплата временно недоступна", show_alert=True)
        return
    if method == "test" and not _is_test_mode_available(callback.from_user.id):
        await callback.answer("Тестовый режим отключен", show_alert=True)
        return

    async with get_session() as session:
        product = await get_product_by_id(session, product_id)
        stock_map = await get_stock_map(session, [product_id])

    if product is None or not product.is_active:
        await callback.answer("Товар недоступен", show_alert=True)
        return
    if method == "fiat" and not _is_fiat_available_for_product(product.slug):
        await callback.answer("Фиат-оплата временно недоступна", show_alert=True)
        return

    stock = stock_map.get(product_id, 0)
    if stock < 1:
        await callback.answer("Недостаточно в наличии", show_alert=True)
        return

    normalized_qty = max(1, min(qty, stock))
    await _safe_edit(
        callback,
        _quantity_screen_text(product, stock, normalized_qty, method),
        quantity_selector_keyboard(
            product_id,
            method,
            normalized_qty,
            min_qty=1,
            max_qty=stock,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("qtygo:"))
async def on_qty_go(callback: CallbackQuery) -> None:
    try:
        _, raw_product_id, raw_method, raw_qty = callback.data.split(":", maxsplit=3)
        product_id = int(raw_product_id)
        qty = int(raw_qty)
    except (TypeError, ValueError):
        await callback.answer("Некорректные параметры", show_alert=True)
        return

    method = _normalize_payment_method(raw_method)
    if method is None:
        await callback.answer("Некорректный способ оплаты", show_alert=True)
        return

    if qty < 1:
        await callback.answer("Количество должно быть больше нуля", show_alert=True)
        return
    if method == "pick":
        async with get_session() as session:
            product = await get_product_by_id(session, product_id)
            stock_map = await get_stock_map(session, [product_id])
        if product is None or not product.is_active:
            await callback.answer("Товар недоступен", show_alert=True)
            return
        stock = stock_map.get(product_id, 0)
        if stock < 1:
            await callback.answer("Недостаточно в наличии", show_alert=True)
            return

        normalized_qty = max(1, min(qty, stock))
        fiat_available = _is_fiat_available_for_product(product.slug) and normalized_qty == 1
        text = (
            "<b>Выбор способа оплаты</b>\n\n"
            f"Товар: <b>{escape(product.title)}</b>\n"
            f"В наличии: <code>{stock}</code>\n"
            f"Выбрано: <code>{normalized_qty}</code>\n\n"
            "<i>Криптой можно оплатить любое количество.</i>\n"
            "<i>Фиатом можно оплатить только 1 шт за заказ.</i>\n\n"
            "<i>Выберите способ оплаты.</i>"
        )
        if settings.payment_test_enabled and product.slug == settings.payment_test_product_slug:
            text = (
                f"{text}\n\n"
                f"<blockquote>Тестовые цены: крипта <code>${settings.payment_test_crypto_price_cents / 100:.2f}</code>, "
                f"фиат <code>${settings.payment_test_fiat_price_cents / 100:.2f}</code>.</blockquote>"
            )
        await _safe_edit(
            callback,
            text,
            payment_methods_keyboard(
                product_id,
                normalized_qty,
                cryptobot_enabled=_is_crypto_available(),
                tribute_enabled=fiat_available,
                test_mode_enabled=_is_test_mode_available(callback.from_user.id),
            ),
        )
        await callback.answer()
        return

    await _start_checkout(callback, product_id, method, qty)


@router.callback_query(F.data.startswith("paycancel:"))
async def on_pay_cancel(callback: CallbackQuery) -> None:
    _, _, order_id = callback.data.partition(":")
    order_id = order_id.strip()
    if not order_id:
        await callback.answer("Некорректный заказ", show_alert=True)
        return

    async with get_session() as session:
        order = await get_order(session, order_id)
        if order is None or order.tg_user_id != callback.from_user.id:
            await callback.answer("Заказ не найден", show_alert=True)
            return

        if order.status in {OrderStatus.PAID, OrderStatus.DELIVERED}:
            await callback.answer("Заказ уже оплачен", show_alert=True)
            return

        await cancel_pending_order(
            session,
            order_id=order_id,
            user_id=callback.from_user.id,
        )

    task = _checkout_timeout_tasks.pop(order_id, None)
    if task and not task.done():
        task.cancel()

    await _safe_edit(callback, *main_menu_payload(settings, callback.from_user.id))
    if callback.message:
        _main_menu_message_id[callback.from_user.id] = callback.message.message_id
    await callback.answer("Оплата отменена")


async def _start_checkout(callback: CallbackQuery, product_id: int, method: str, qty: int) -> None:
    if method == "crypto" and not _is_crypto_available():
        await callback.answer("Крипто-оплата временно недоступна", show_alert=True)
        return
    if method == "test" and not _is_test_mode_available(callback.from_user.id):
        await callback.answer("Тестовый режим отключен", show_alert=True)
        return
    if method == "fiat" and qty != 1:
        await callback.answer("Фиат: доступна покупка только 1 шт.", show_alert=True)
        return

    async with get_session() as session:
        product = await get_product_by_id(session, product_id)
        stock_map = await get_stock_map(session, [product_id])

        if product is None or not product.is_active:
            await callback.answer("Товар недоступен", show_alert=True)
            return
        if method == "fiat" and not _is_fiat_available_for_product(product.slug):
            await callback.answer("Фиат-оплата временно недоступна", show_alert=True)
            return

        stock = stock_map.get(product_id, 0)
        if stock < qty:
            await callback.answer("Недостаточно товара в наличии", show_alert=True)
            return

        if method == "crypto":
            order = await create_order_with_reservation(
                session,
                user_id=callback.from_user.id,
                username=callback.from_user.username,
                product=product,
                quantity=qty,
                payment_method=PaymentMethod.CRYPTO,
                unit_price_cents=_effective_unit_price_cents(product, "crypto"),
            )
            if order is None:
                await callback.answer("Недостаточно товара в наличии", show_alert=True)
                return

            try:
                invoice = await crypto_client.create_invoice(
                    order_id=order.id,
                    amount_usd_cents=order.total_price,
                    product_title=product.title,
                    quantity=qty,
                )
            except Exception:
                await callback.answer(
                    "Не удалось создать крипто-инвойс. Проверьте CRYPTOBOT_API_TOKEN в .env.",
                    show_alert=True,
                )
                return

            await _safe_edit(
                callback,
                "<b>Оплата криптой</b>\n\n"
                "1. Нажмите кнопку ниже.\n"
                "2. Оплатите инвойс в Crypto Bot.\n"
                "3. После webhook-подтверждения заказ будет выдан автоматически.",
                cryptobot_checkout_keyboard(invoice.pay_url, order.id),
            )
            if callback.message:
                _schedule_checkout_timeout(
                    bot=callback.bot,
                    order_id=order.id,
                    chat_id=callback.message.chat.id,
                    message_id=callback.message.message_id,
                    user_id=callback.from_user.id,
                )
            await callback.answer()
            return

        if method == "fiat":
            order = await create_order_with_reservation(
                session,
                user_id=callback.from_user.id,
                username=callback.from_user.username,
                product=product,
                quantity=qty,
                payment_method=PaymentMethod.FIAT,
                unit_price_cents=_effective_unit_price_cents(product, "fiat"),
            )
            if order is None:
                await callback.answer("Недостаточно товара в наличии", show_alert=True)
                return

            tribute_url = build_tribute_url_for_product(
                product_slug=product.slug,
                fallback_base_url=settings.tribute_base_url,
                tribute_link_gpt_pro_1m=settings.tribute_link_gpt_pro_1m,
                tribute_link_gpt_pro_3m=settings.tribute_link_gpt_pro_3m,
                tribute_link_lovable_100=settings.tribute_link_lovable_100,
                tribute_link_lovable_200=settings.tribute_link_lovable_200,
                tribute_link_lovable_300=settings.tribute_link_lovable_300,
                tribute_link_replit_core=settings.tribute_link_replit_core,
                tribute_link_replit_team=settings.tribute_link_replit_team,
                order_id=order.id,
                user_id=callback.from_user.id,
                amount_usd_cents=order.total_price,
                quantity=qty,
            )
            if not tribute_url:
                await callback.answer("Фиат-ссылка не настроена", show_alert=True)
                return
            await _safe_edit(
                callback,
                "<b>Оплата фиатом</b>\n\n"
                "1. Нажмите кнопку ниже.\n"
                "2. Завершите оплату на стороне Tribute.\n"
                "3. После webhook-подтверждения заказ будет выдан автоматически.",
                tribute_checkout_keyboard(tribute_url, order.id),
            )
            if callback.message:
                _schedule_checkout_timeout(
                    bot=callback.bot,
                    order_id=order.id,
                    chat_id=callback.message.chat.id,
                    message_id=callback.message.message_id,
                    user_id=callback.from_user.id,
                )
            await callback.answer()
            return

        order = await create_order_with_reservation(
            session,
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            product=product,
            quantity=qty,
            payment_method=PaymentMethod.CRYPTO,
        )
        if order is None:
            await callback.answer("Недостаточно товара в наличии", show_alert=True)
            return

        paid = await mark_order_paid(
            session,
            order_id=order.id,
            provider_charge_id="test-mode",
            telegram_payment_charge_id="test-mode",
        )
        if paid is None:
            await callback.answer("Не удалось провести тестовый заказ", show_alert=True)
            return

        csv_path = await deliver_order_csv(
            session,
            order_id=order.id,
            export_dir=settings.export_dir,
        )

    if csv_path is None:
        await callback.answer("Не удалось сформировать CSV", show_alert=True)
        return
    await _safe_edit(callback, *main_menu_payload(settings, callback.from_user.id))
    if callback.message:
        _main_menu_message_id[callback.from_user.id] = callback.message.message_id
    if callback.message:
        doc_message = await callback.message.answer_document(
            document=FSInputFile(str(csv_path)),
            caption=f"Тестовый заказ <code>{order.id[:8]}</code>",
            parse_mode="HTML",
        )
        try:
            await doc_message.pin(disable_notification=True)
        except TelegramBadRequest:
            pass
    await callback.answer("Готово")


@router.message(F.text & ~F.text.startswith("/"))
async def cleanup_text_messages(message: Message) -> None:
    await _safe_delete_user_message(message)
