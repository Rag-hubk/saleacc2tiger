from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from saleacc_bot.config import Settings
from saleacc_bot.keyboards import main_menu_keyboard
from saleacc_bot.models import Order, Product
from saleacc_bot.services.catalog import get_product_spec

MAIN_MENU_TEXT = (
    "<b>Продажа подписок ChatGPT</b>\n\n"
    "Внутри бота доступны <b>ChatGPT Plus</b> и линейка <b>ChatGPT Pro</b> на разные сроки.\n"
    "Перед оплатой бот запросит e-mail для чека, затем переведет на оплату через <b>ЮKassa</b>."
)


def is_admin(settings: Settings, user_id: int) -> bool:
    return user_id in settings.admin_ids


def main_menu_payload(settings: Settings, user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    return MAIN_MENU_TEXT, main_menu_keyboard(is_admin=is_admin(settings, user_id), support_url=settings.support_url)


def catalog_text(products: list[Product]) -> str:
    plus_product = next((product for product in products if product.slug == "gpt-plus-1m"), None)
    pro_products = [product for product in products if product.slug.startswith("gpt-pro-")]

    lines = [
        "<b>Каталог подписок</b>",
        "",
        "Выберите подходящий вариант:",
        "",
    ]
    if plus_product is not None:
        lines.append(f"<b>ChatGPT Plus</b> - от <code>{format_price(plus_product.price_kopecks)}</code>")
        lines.append("Для повседневной работы, учебы, контента и кода.")
        lines.append("")
    if pro_products:
        min_pro_price = min(product.price_kopecks for product in pro_products)
        lines.append(f"<b>ChatGPT Pro</b> - от <code>{format_price(min_pro_price)}</code>")
        lines.append("Для плотной профессиональной загрузки и максимальных лимитов.")
        lines.append("")
    lines.append("<i>Нажмите на раздел, чтобы посмотреть состав и перейти к оплате.</i>")
    return "\n".join(lines)


def product_text(product: Product) -> str:
    spec = get_product_spec(product.slug)
    features = spec.features if spec else ()
    if product.slug == "gpt-plus-1m":
        lines = [
            "<b>ChatGPT Plus</b>",
            "",
            "Оптимальный тариф, если нужен быстрый и удобный доступ к возможностям ChatGPT без перегруза по цене.",
            "",
            "<b>Подходит для:</b>",
            "- ежедневной работы и учебы",
            "- написания текста, анализа файлов и базового кода",
            "- использования Codex и мультимодальных инструментов",
            "",
            f"Цена: <code>{format_price(product.price_kopecks)}</code>",
        ]
    else:
        lines = [
            f"<b>{product.title}</b>",
            "",
            "Премиальный тариф для тех, кто использует ChatGPT как основной рабочий инструмент и хочет максимум лимитов.",
            "",
            "<b>Подходит для:</b>",
            "- интенсивной работы с Codex и кодовыми задачами",
            "- длинных сессий без постоянных ограничений",
            "- активного использования Sora и исследовательских инструментов",
            "",
            f"Цена: <code>{format_price(product.price_kopecks)}</code>",
        ]
        if product.slug == "gpt-pro-3m":
            lines.append("Формат на 3 месяца для стабильной работы без ежемесячного продления.")
        if product.slug == "gpt-pro-6m":
            lines.append("Формат на 6 месяцев для долгого периода без повторных покупок.")
    if features:
        lines.append("")
        lines.append("<b>Что внутри:</b>")
        lines.extend(f"- {feature}" for feature in features)
    return "\n".join(lines)


def pro_group_text(products: list[Product]) -> str:
    lines = [
        "<b>ChatGPT Pro</b>",
        "",
        "Тарифная линейка для тех, кому нужен максимум по скорости, лимитам и рабочим инструментам OpenAI.",
        "",
        "<b>Что получает клиент:</b>",
        "- высокий рабочий лимит на модели и инструменты",
        "- расширенный сценарий работы с Codex",
        "- больше пространства для Sora и исследовательских задач",
        "- удобный выбор срока под бюджет и нагрузку",
        "",
        "<b>Варианты:</b>",
    ]
    for product in sorted(products, key=lambda item: item.sort_order):
        lines.append(f"- {product.title}: <code>{format_price(product.price_kopecks)}</code>")
    return "\n".join(lines)


def payment_caption(*, product: Product, email: str, order_id: str, offer_url: str) -> str:
    return (
        "<b>Заказ создан</b>\n\n"
        f"Тариф: <b>{product.title}</b>\n"
        f"Сумма: <code>{format_price(product.price_kopecks)}</code>\n"
        f"E-mail для чека: <code>{email}</code>\n"
        f"Заказ: <code>{order_id[:8]}</code>\n\n"
        f"Оплачивая заказ, вы подтверждаете согласие с <a href=\"{offer_url}\">публичной офертой</a>."
    )


def orders_text(orders: list[Order]) -> str:
    if not orders:
        return "<b>Мои заказы</b>\n\n<i>Заказов пока нет.</i>"
    lines = ["<b>Мои заказы</b>", ""]
    for order in orders:
        lines.append(
            f"<code>{order.id[:8]}</code> | <b>{order.product_title}</b> | "
            f"{format_order_status(order.status)} | <code>{format_price(order.total_price)}</code>"
        )
    return "\n".join(lines)


def format_order_status(status: str) -> str:
    labels = {
        "pending_payment": "ожидает оплату",
        "paid": "оплачен",
        "cancelled": "отменен",
        "failed": "ошибка",
    }
    return labels.get(status, status)


def format_price(kopecks: int) -> str:
    rubles = kopecks / 100
    return f"{rubles:,.2f} RUB".replace(",", " ")
