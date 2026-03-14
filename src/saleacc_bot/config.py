from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv
from saleacc_bot.url_utils import normalize_public_url

load_dotenv()


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value in {"...", "replace_me", "replace_with_value"}:
        raise RuntimeError(f"Environment variable {name} is required")
    return value


def _optional_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value in {"...", "replace_me", "replace_with_value"}:
        return ""
    return value


def _parse_admin_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


def _parse_int(raw: str | None, default: int) -> int:
    if raw is None or not raw.strip():
        return default
    return int(raw.strip())


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: list[int]
    support_url: str
    public_offer_url: str

    database_url: str

    google_sheet_id: str
    google_service_account_file: str
    google_service_account_json: str
    google_service_account_json_b64: str
    google_inventory_worksheet: str
    google_sales_worksheet: str
    chatgpt_stock_reserve_minutes: int

    yookassa_shop_id: str
    yookassa_secret_key: str
    yookassa_return_url: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        bot_token=_require_env("TELEGRAM_BOT_TOKEN"),
        admin_ids=_parse_admin_ids(os.getenv("TELEGRAM_ADMIN_IDS")),
        support_url=normalize_public_url(os.getenv("SUPPORT_URL", "https://t.me/your_support_username")),
        public_offer_url=normalize_public_url(os.getenv("PUBLIC_OFFER_URL", "https://example.com/oferta")),
        database_url=_require_env("DATABASE_URL"),
        google_sheet_id=_require_env("GOOGLE_SHEET_ID"),
        google_service_account_file=_optional_env("GOOGLE_SERVICE_ACCOUNT_FILE"),
        google_service_account_json=_optional_env("GOOGLE_SERVICE_ACCOUNT_JSON"),
        google_service_account_json_b64=_optional_env("GOOGLE_SERVICE_ACCOUNT_JSON_B64"),
        google_inventory_worksheet=os.getenv("GOOGLE_INVENTORY_WORKSHEET", "inventory").strip() or "inventory",
        google_sales_worksheet=os.getenv("GOOGLE_SALES_WORKSHEET", "sales").strip() or "sales",
        chatgpt_stock_reserve_minutes=_parse_int(os.getenv("CHATGPT_STOCK_RESERVE_MINUTES"), 20),
        yookassa_shop_id=_require_env("YOOKASSA_SHOP_ID"),
        yookassa_secret_key=_require_env("YOOKASSA_SECRET_KEY"),
        yookassa_return_url=_require_env("YOOKASSA_RETURN_URL"),
    )
