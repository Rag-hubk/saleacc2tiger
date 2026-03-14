from __future__ import annotations

from pathlib import Path

from aiogram.types import InlineKeyboardMarkup

from saleacc_bot.config import Settings
from saleacc_bot.keyboards import main_menu_keyboard
from saleacc_bot.models import Order, Product
from saleacc_bot.services.catalog import get_product_category, get_product_spec
from saleacc_bot.url_utils import is_valid_http_url

MAIN_MENU_TEXT = (
    "👋 <b>Добро пожаловать в NH | STORE01!</b>\n\n"
    "Мы продаём подписки на ChatGPT и Google Gemini в 2-3 раза дешевле, чем напрямую. "
    "Оплата в рублях, без иностранных карт, без танцев с VPN при покупке.\n\n"
    "🔹 <b>Почему нам доверяют:</b>\n\n"
    "👤 Персональный аккаунт — ты единственный пользователь, никакого шаринга\n"
    "💰 Экономия до 68% — платишь от 499₽ вместо 1 580₽\n"
    "⚡ GPT выдаём автоматически, Gemini — в течение 1-24 часов\n"
    "🛡️ Гарантия 100% — если что-то не так, бесплатная замена\n"
    "🎁 VPN в подарок — настроим, чтобы всё работало\n"
    "💳 Оплата — карты РФ, СБП\n\n"
    "📌 <b>Выбери раздел:</b>\n"
    "🟢 ChatGPT — Plus / Pro\n"
    "🔵 Gemini — Ultra"
)

SECTION_TEXTS = {
    "chatgpt": (
        "🧠 <b>ChatGPT — самая мощная нейросеть в мире</b>\n\n"
        "Из России официально не оплатить — нужна иностранная карта и адрес за рубежом. "
        "У нас всё проще: выбрал → оплатил → получил свой персональный аккаунт.\n\n"
        "👤 Каждый аккаунт — персональный. Ты единственный пользователь.\n"
        "🛡️ Гарантия 100% — замена при любой проблеме\n"
        "⚡ Автовыдача — аккаунт за 1 минуту после оплаты\n"
        "🎁 VPN в подарок — настроим, поможем\n\n"
        "👇 <b>Выбери тариф:</b>"
    ),
    "gemini": (
        "💎 <b>Google Gemini Ultra — вся мощь AI от Google</b>\n\n"
        "Gemini Ultra — это максимальная подписка Google AI: генерация видео, картинок, исследования, "
        "AI-агенты и 30 ТБ облака. Официально стоит $249.99/мес и недоступна в России напрямую.\n\n"
        "👤 Персональный аккаунт — только ты пользуешься\n"
        "🛡️ Гарантия 100% — замена при любой проблеме\n"
        "⏳ Выдача — в течение 1-24 часов после оплаты\n"
        "🎁 VPN в подарок — настроим, поможем\n\n"
        "👇 <b>Выбрать:</b>"
    ),
}

_IMAGE_DIR = Path(__file__).resolve().parents[2] / "image"
MAIN_MENU_IMAGE = _IMAGE_DIR / "стартфото.jpeg"
SECTION_IMAGES = {
    "chatgpt": _IMAGE_DIR / "Раздел ChatGPT.jpeg",
    "gemini": _IMAGE_DIR / "Раздел Gemini.jpeg",
}


def is_admin(settings: Settings, user_id: int) -> bool:
    return user_id in settings.admin_ids


def main_menu_payload(settings: Settings, user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    return MAIN_MENU_TEXT, main_menu_keyboard(is_admin=is_admin(settings, user_id))


def main_menu_image_path() -> Path:
    return MAIN_MENU_IMAGE


def section_image_path(category: str) -> Path | None:
    return SECTION_IMAGES.get(category)


def section_text(category: str) -> str:
    return SECTION_TEXTS[category]


def product_text(product: Product) -> str:
    spec = get_product_spec(product.slug)
    if spec is None:
        return f"<b>{product.title}</b>\n\n<code>{format_price(product.price_kopecks)}</code>"

    savings = spec.official_price_kopecks - spec.price_kopecks
    lines = [
        f"<b>{spec.button_title}</b>",
        f"Официальная цена: {format_price(spec.official_price_kopecks)} | Экономия: {format_price(savings)}",
        "",
        "<b>Что входит:</b>",
    ]
    lines.extend(f"- {feature}" for feature in spec.features)
    lines.extend(("", spec.audience))
    return "\n".join(lines)


def payment_caption(*, product: Product, email: str, order_id: str, offer_url: str) -> str:
    category = get_product_category(product.slug)
    delivery_block = (
        "Аккаунт уже зарезервирован на 20 минут. После успешной оплаты доступ придет автоматически в этого бота."
        if category == "chatgpt"
        else "После оплаты доступ по этому тарифу выдается вручную в бота в течение 1-24 часов."
    )
    offer_line = (
        f"Оплачивая заказ, вы подтверждаете согласие с <a href=\"{offer_url}\">публичной офертой</a>."
        if is_valid_http_url(offer_url)
        else "Оплачивая заказ, вы подтверждаете согласие с публичной офертой."
    )
    return (
        "<b>Заказ оформлен</b>\n\n"
        f"<b>Тариф:</b> {product.title}\n"
        f"<b>Сумма:</b> <code>{format_price(product.price_kopecks)}</code>\n"
        f"<b>E-mail для чека:</b> <code>{email}</code>\n"
        f"<b>Номер заказа:</b> <code>{order_id[:8]}</code>\n\n"
        f"<blockquote>{delivery_block}</blockquote>\n\n"
        f"{offer_line}"
    )


def orders_text(orders: list[Order]) -> str:
    if not orders:
        return "<b>Мои заказы</b>\n\n<i>Заказов пока нет.</i>"
    lines = ["<b>Мои заказы</b>", ""]
    for order in orders:
        lines.append(f"<code>{order.id[:8]}</code> • <b>{order.product_title}</b>")
        lines.append(f"{format_order_status(order.status)} • <code>{format_price(order.total_price)}</code>")
        lines.append("")
    return "\n".join(lines)


def format_order_status(status: str) -> str:
    labels = {
        "pending_payment": "Ожидает оплаты",
        "paid": "Оплачен",
        "cancelled": "Отменен",
        "failed": "Ошибка оплаты",
    }
    return labels.get(status, status)


def format_price(kopecks: int) -> str:
    if kopecks % 100 == 0:
        rubles = kopecks // 100
        return f"{rubles:,}₽".replace(",", " ")
    rubles = kopecks / 100
    return f"{rubles:,.2f}₽".replace(",", " ")
