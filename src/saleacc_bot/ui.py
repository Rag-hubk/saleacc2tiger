from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from saleacc_bot.config import Settings
from saleacc_bot.keyboards import main_menu_keyboard

MAIN_MENU_TEXT = (
    "<b>Премиум-доступы к топовым AI-сервисам</b>\n\n"
    "<b>GPT Pro</b> от <code>$50</code> • <b>Lovable AI Pro</b> от <code>$15</code> • <b>Replit</b> от <code>$15</code>\n\n"
    "Оплата: <b>только криптовалютой</b> через Crypto Bot.\n"
    "После подтверждения оплаты доступы приходят в личный чат в формате CSV.\n\n"
    "<blockquote>Прозрачные условия, быстрый процесс и поддержка.</blockquote>\n"
    "<i>Выберите нужный раздел ниже.</i>"
)


def is_admin(settings: Settings, user_id: int) -> bool:
    return user_id in settings.admin_ids


def main_menu_payload(settings: Settings, user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    return MAIN_MENU_TEXT, main_menu_keyboard(is_admin=is_admin(settings, user_id), support_url=settings.support_url)
