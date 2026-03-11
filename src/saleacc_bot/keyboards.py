from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from saleacc_bot.models import Product


def _button(text: str, *, callback_data: str | None = None, url: str | None = None) -> InlineKeyboardButton:
    if callback_data is not None:
        return InlineKeyboardButton(text=text, callback_data=callback_data)
    return InlineKeyboardButton(text=text, url=url)


def main_menu_keyboard(*, is_admin: bool, support_url: str) -> InlineKeyboardMarkup:
    rows = [
        [_button("Каталог", callback_data="catalog")],
        [_button("Мои заказы", callback_data="orders"), _button("Поддержка", url=support_url)],
    ]
    if is_admin:
        rows.append([_button("Админ", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def catalog_keyboard(products: list[Product]) -> InlineKeyboardMarkup:
    plus_product = next((product for product in products if product.slug == "gpt-plus-1m"), None)
    pro_products = [product for product in products if product.slug.startswith("gpt-pro-")]

    rows: list[list[InlineKeyboardButton]] = []
    if plus_product is not None:
        rows.append([_button("ChatGPT Plus", callback_data=f"product:{plus_product.slug}")])
    if pro_products:
        rows.append([_button("ChatGPT Pro", callback_data="group:pro")])
    rows.append([_button("Назад", callback_data="main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_keyboard(product_slug: str, *, back_callback: str = "catalog") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Купить", callback_data=f"buy:{product_slug}")],
            [_button("Назад", callback_data=back_callback)],
        ]
    )


def pro_group_keyboard(products: list[Product]) -> InlineKeyboardMarkup:
    rows = [
        [_button(product.title, callback_data=f"product:{product.slug}")]
        for product in sorted(products, key=lambda item: item.sort_order)
    ]
    rows.append([_button("Назад", callback_data="catalog")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def email_choice_keyboard(*, product_slug: str, email: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button(f"Использовать {email}", callback_data=f"email_use:{product_slug}")],
            [_button("Ввести другой e-mail", callback_data=f"email_change:{product_slug}")],
            [_button("Назад", callback_data=f"product:{product_slug}")],
        ]
    )


def pay_order_keyboard(*, confirmation_url: str, order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Перейти к оплате", url=confirmation_url)],
            [_button("Проверить оплату", callback_data=f"order_check:{order_id}")],
            [_button("Отменить заказ", callback_data=f"order_cancel:{order_id}")],
        ]
    )


def orders_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_button("Назад", callback_data="main")]])


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Статистика", callback_data="admin_stats")],
            [_button("Последние заказы", callback_data="admin_orders")],
            [_button("Назад", callback_data="main")],
        ]
    )


def admin_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Назад", callback_data="admin_panel")],
        ]
    )
