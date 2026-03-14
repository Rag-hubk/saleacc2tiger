from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from saleacc_bot.models import Product
from saleacc_bot.services.catalog import get_product_spec


def _button(text: str, *, callback_data: str | None = None, url: str | None = None) -> InlineKeyboardButton:
    if callback_data is not None:
        return InlineKeyboardButton(text=text, callback_data=callback_data)
    return InlineKeyboardButton(text=text, url=url)


def main_menu_keyboard(*, is_admin: bool, support_url: str) -> InlineKeyboardMarkup:
    rows = [
        [_button("🟢 ChatGPT", callback_data="section:chatgpt"), _button("🔵 Gemini", callback_data="section:gemini")],
        [_button("Мои заказы", callback_data="orders"), _button("Поддержка", url=support_url)],
    ]
    if is_admin:
        rows.append([_button("Админ", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def section_keyboard(products: list[Product], *, back_callback: str = "main") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for product in products:
        spec = get_product_spec(product.slug)
        label = spec.button_title if spec is not None else product.title
        rows.append([_button(label, callback_data=f"product:{product.slug}")])
    rows.append([_button("Назад", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_keyboard(product_slug: str, *, back_callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Оформить заказ", callback_data=f"buy:{product_slug}")],
            [_button("Назад", callback_data=back_callback)],
        ]
    )


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
            [_button("Оплатить через ЮKassa", url=confirmation_url)],
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
    return InlineKeyboardMarkup(inline_keyboard=[[_button("Назад", callback_data="admin_panel")]])
