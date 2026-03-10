from __future__ import annotations

from collections.abc import Iterable

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from saleacc_bot.models import Product


def _inline_button(
    text: str,
    *,
    callback_data: str | None = None,
    url: str | None = None,
    style: str | None = None,
) -> InlineKeyboardButton:
    payload: dict[str, str] = {"text": text}
    if callback_data is not None:
        payload["callback_data"] = callback_data
    if url is not None:
        payload["url"] = url
    if style:
        payload["style"] = style
    try:
        return InlineKeyboardButton.model_validate(payload)
    except Exception:
        if callback_data is not None:
            return InlineKeyboardButton(text=text, callback_data=callback_data)
        return InlineKeyboardButton(text=text, url=url)


def main_menu_keyboard(*, is_admin: bool, support_url: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [_inline_button("Каталог", callback_data="catalog", style="primary")],
        [_inline_button("Мои заказы", callback_data="orders"), _inline_button("Поддержка", url=support_url)],
    ]
    if is_admin:
        rows.append([_inline_button("Admin", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def catalog_keyboard(
    _products: Iterable[Product],
    _stock_by_product: dict[int, int],
    *,
    buy_crypto_url: str | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            _inline_button("𖣔 GPT Pro", callback_data="group:gpt-pro"),
            _inline_button("◈ Gemini", callback_data="group:gemini"),
        ],
        [
            _inline_button("♡ Lovable", callback_data="group:lovable"),
            _inline_button("▚ Replit", callback_data="group:replit"),
        ],
    ]
    if buy_crypto_url:
        rows.append([_inline_button("Удобно купить крипту тут", url=buy_crypto_url)])
    rows.append([_inline_button("Назад", callback_data="main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def group_details_keyboard(
    variants: list[tuple[int, str, int, int]],
    *,
    buy_crypto_url: str | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for product_id, label, price_cents, stock in variants:
        if stock > 0:
            rows.append([_inline_button(f"{label} · ${price_cents / 100:.0f}", callback_data=f"buy:{product_id}")])
        else:
            rows.append([_inline_button(f"{label} · нет в наличии", callback_data="noop")])
    if buy_crypto_url:
        rows.append([_inline_button("Удобно купить крипту тут", url=buy_crypto_url)])
    rows.append([_inline_button("Назад", callback_data="catalog")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_methods_keyboard(
    product_id: int,
    qty: int,
    *,
    cryptobot_enabled: bool,
    tribute_enabled: bool,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if cryptobot_enabled:
        rows.append([_inline_button("Криптой", callback_data=f"paymethod:{product_id}:crypto:{qty}")])
    rows.append([_inline_button("Назад", callback_data=f"qtyset:{product_id}:pick:{qty}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quantity_selector_keyboard(
    product_id: int,
    payment_method: str,
    qty: int,
    *,
    min_qty: int,
    max_qty: int,
    buy_crypto_url: str | None = None,
) -> InlineKeyboardMarkup:
    dec_qty = qty - 1 if qty > min_qty else qty
    inc_qty = qty + 1 if qty < max_qty else qty
    rows: list[list[InlineKeyboardButton]] = [
        [
            _inline_button("−", callback_data=f"qtyset:{product_id}:{payment_method}:{dec_qty}"),
            _inline_button(f"{qty}", callback_data="noop"),
            _inline_button("+", callback_data=f"qtyset:{product_id}:{payment_method}:{inc_qty}"),
        ],
    ]
    if max_qty >= 6:
        dec5 = qty - 5 if qty - 5 >= min_qty else min_qty
        inc5 = qty + 5 if qty + 5 <= max_qty else max_qty
        rows.append(
            [
                _inline_button("−5", callback_data=f"qtyset:{product_id}:{payment_method}:{dec5}"),
                _inline_button("+5", callback_data=f"qtyset:{product_id}:{payment_method}:{inc5}"),
            ]
        )
    proceed_text = "К оплате" if payment_method == "pick" else "Продолжить"
    back_callback = "catalog" if payment_method == "pick" else f"qtyset:{product_id}:pick:{qty}"
    rows.extend(
        [
            [_inline_button(proceed_text, callback_data=f"qtygo:{product_id}:{payment_method}:{qty}")],
        ]
    )
    if buy_crypto_url:
        rows.append([_inline_button("Удобно купить крипту тут", url=buy_crypto_url)])
    rows.append([_inline_button("Назад", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tribute_checkout_keyboard(url: str, order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_inline_button("Перейти к оплате картой", url=url)],
            [_inline_button("Отменить оплату", callback_data=f"paycancel:{order_id}", style="danger")],
        ]
    )


def cryptobot_checkout_keyboard(url: str, order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_inline_button("Оплатить криптой", url=url)],
            [_inline_button("Отменить оплату", callback_data=f"paycancel:{order_id}", style="danger")],
        ]
    )


def orders_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_inline_button("Назад", callback_data="main")],
        ]
    )


def support_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_inline_button("Назад", callback_data="main")],
        ]
    )


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_inline_button("Статистика", callback_data="admin_stats"), _inline_button("Продажи", callback_data="admin_sales")],
            [_inline_button("Покупатели", callback_data="admin_buyers:0"), _inline_button("Не оплатили", callback_data="admin_abandoned:0")],
            [_inline_button("Рассылка", callback_data="admin_broadcast_menu")],
            [_inline_button("Назад", callback_data="main")],
        ]
    )


def admin_stats_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_inline_button("Обновить", callback_data="admin_stats")],
            [_inline_button("Назад", callback_data="admin_panel")],
        ]
    )


def admin_sales_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_inline_button("Обновить", callback_data="admin_sales")],
            [_inline_button("Назад", callback_data="admin_panel")],
        ]
    )


def admin_paginated_keyboard(*, prefix: str, page: int, total_pages: int) -> InlineKeyboardMarkup:
    safe_page = max(0, page)
    safe_total = max(1, total_pages)

    rows: list[list[InlineKeyboardButton]] = []
    nav_row: list[InlineKeyboardButton] = []

    if safe_page > 0:
        nav_row.append(_inline_button("← Назад", callback_data=f"{prefix}:{safe_page - 1}"))
    nav_row.append(_inline_button(f"{safe_page + 1}/{safe_total}", callback_data="noop"))
    if safe_page + 1 < safe_total:
        nav_row.append(_inline_button("Вперёд →", callback_data=f"{prefix}:{safe_page + 1}"))

    rows.append(nav_row)
    rows.append([_inline_button("В админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_broadcast_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_inline_button("Новая рассылка", callback_data="admin_broadcast_start")],
            [_inline_button("Назад", callback_data="admin_panel")],
        ]
    )


def admin_broadcast_segment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_inline_button("Все пользователи", callback_data="admin_broadcast_segment:all")],
            [_inline_button("Не оплатили", callback_data="admin_broadcast_segment:abandoned")],
            [_inline_button("Отмена", callback_data="admin_broadcast_cancel")],
        ]
    )


def admin_broadcast_add_button_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_inline_button("Добавить Inline кнопку", callback_data="admin_broadcast_button:yes")],
            [_inline_button("Без кнопки", callback_data="admin_broadcast_button:no")],
            [_inline_button("Отмена", callback_data="admin_broadcast_cancel")],
        ]
    )


def admin_broadcast_preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_inline_button("Отправить", callback_data="admin_broadcast_send")],
            [_inline_button("Собрать заново", callback_data="admin_broadcast_start")],
            [_inline_button("Отмена", callback_data="admin_broadcast_cancel")],
        ]
    )
