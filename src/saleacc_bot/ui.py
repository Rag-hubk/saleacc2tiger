from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from saleacc_bot.config import Settings
from saleacc_bot.keyboards import main_menu_keyboard
from saleacc_bot.models import Order, Product
from saleacc_bot.services.catalog import get_product_spec

MAIN_MENU_TEXT = (
    "<b>Подписки ChatGPT</b>\n\n"
    "В боте доступны <b>ChatGPT Plus</b> и <b>ChatGPT Pro</b> на разные сроки.\n"
    "Оплата проходит через <b>ЮKassa</b> в рублях."
    "\n\n<blockquote>Перед оплатой бот запросит e-mail для электронного чека.</blockquote>"
)


def is_admin(settings: Settings, user_id: int) -> bool:
    return user_id in settings.admin_ids


def main_menu_payload(settings: Settings, user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    return MAIN_MENU_TEXT, main_menu_keyboard(is_admin=is_admin(settings, user_id), support_url=settings.support_url)


def catalog_text(products: list[Product]) -> str:
    plus_product = next((product for product in products if product.slug == "gpt-plus-1m"), None)
    pro_products = [product for product in products if product.slug.startswith("gpt-pro-")]

    lines = [
        "<b>Каталог ChatGPT</b>",
        "",
        "Подберите тариф под свою нагрузку: повседневная работа, учеба, код или интенсивные рабочие сценарии.",
        "",
    ]
    if plus_product is not None:
        lines.append(f"<b>ChatGPT Plus</b> • <code>{format_price(plus_product.price_kopecks)}</code>")
        lines.append("Для ежедневных задач, учебы, документов, контента и рабочих запросов.")
        lines.append("")
    if pro_products:
        min_pro_price = min(product.price_kopecks for product in pro_products)
        lines.append(f"<b>ChatGPT Pro</b> • от <code>{format_price(min_pro_price)}</code>")
        lines.append("Для высокой нагрузки, длинных сессий и максимальных лимитов.")
        lines.append("")
    lines.append("<blockquote>Откройте раздел, чтобы посмотреть состав тарифа и перейти к оформлению.</blockquote>")
    return "\n".join(lines)


def product_text(product: Product) -> str:
    spec = get_product_spec(product.slug)
    features = spec.features if spec else ()
    if product.slug == "gpt-plus-1m":
        lines = [
            f"<b>{product.title}</b>",
            "",
            "<blockquote>Тариф для тех, кому нужен стабильный доступ к возможностям ChatGPT без переплаты за максимальные лимиты.</blockquote>",
            "",
            "<b>Подойдет, если вам нужен:</b>",
            "• ежедневный рабочий инструмент для текста, документов и анализа",
            "• комфортный тариф для учебы, контента и базовых кодовых задач",
            "• платный доступ к ключевым возможностям ChatGPT без тарифа Pro",
            "",
            f"<b>Стоимость:</b> <code>{format_price(product.price_kopecks)}</code>",
        ]
    else:
        lines = [
            f"<b>{product.title}</b>",
            "",
            "<blockquote>Премиальный тариф для тех, кто использует ChatGPT как основной рабочий инструмент и не хочет упираться в лимиты.</blockquote>",
            "",
            "<b>Подойдет, если вам нужен:</b>",
            "• интенсивный рабочий режим с высокой нагрузкой",
            "• длинные сессии без постоянных ограничений",
            "• расширенный сценарий для кода, исследований и сложных задач",
            "",
            f"<b>Стоимость:</b> <code>{format_price(product.price_kopecks)}</code>",
        ]
        if product.slug == "gpt-pro-3m":
            lines.append("<i>Формат на 3 месяца без ежемесячного продления.</i>")
        if product.slug == "gpt-pro-6m":
            lines.append("<i>Формат на 6 месяцев для долгого периода без повторных покупок.</i>")
    if features:
        lines.append("")
        lines.append("<b>Что входит:</b>")
        lines.extend(f"• {feature}" for feature in features)
    return "\n".join(lines)


def pro_group_text(products: list[Product]) -> str:
    lines = [
        "<b>ChatGPT Pro</b>",
        "",
        "<blockquote>Линейка для интенсивной работы: больше лимитов, выше приоритет и удобный выбор срока под нагрузку.</blockquote>",
        "",
        "<b>Что получает клиент:</b>",
        "• высокий рабочий лимит на модели и инструменты",
        "• расширенный сценарий работы с кодом и исследовательскими задачами",
        "• выбор срока под бюджет и формат использования",
        "",
        "<b>Варианты:</b>",
    ]
    for product in sorted(products, key=lambda item: item.sort_order):
        lines.append(f"• {product.title} — <code>{format_price(product.price_kopecks)}</code>")
    return "\n".join(lines)


def payment_caption(*, product: Product, email: str, order_id: str, offer_url: str) -> str:
    return (
        "<b>Заказ оформлен</b>\n\n"
        f"<b>Тариф:</b> {product.title}\n"
        f"<b>Сумма:</b> <code>{format_price(product.price_kopecks)}</code>\n"
        f"<b>E-mail для чека:</b> <code>{email}</code>\n"
        f"<b>Номер заказа:</b> <code>{order_id[:8]}</code>\n\n"
        "<blockquote>Нажмите кнопку оплаты ниже. Если статус не обновится автоматически, используйте кнопку проверки.</blockquote>\n\n"
        f"Оплачивая заказ, вы подтверждаете согласие с <a href=\"{offer_url}\">публичной офертой</a>."
    )


def orders_text(orders: list[Order]) -> str:
    if not orders:
        return "<b>Мои заказы</b>\n\n<i>Заказов пока нет.</i>"
    lines = ["<b>Мои заказы</b>", ""]
    for order in orders:
        lines.append(
            f"<code>{order.id[:8]}</code> • <b>{order.product_title}</b>"
        )
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
        return f"{rubles:,} ₽".replace(",", " ")
    rubles = kopecks / 100
    return f"{rubles:,.2f} ₽".replace(",", " ")
