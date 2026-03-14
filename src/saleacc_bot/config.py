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
    google_orders_worksheet: str
    chatgpt_stock_csv_url: str
    chatgpt_stock_csv_path: str
    chatgpt_stock_reserve_minutes: int

    yookassa_shop_id: str
    yookassa_secret_key: str
    yookassa_return_url: str
    yookassa_api_base: str
    yookassa_vat_code: int
    yookassa_tax_system_code: int | None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    tax_system_raw = _optional_env("YOOKASSA_TAX_SYSTEM_CODE")
    return Settings(
        bot_token=_require_env("TELEGRAM_BOT_TOKEN"),
        admin_ids=_parse_admin_ids(os.getenv("TELEGRAM_ADMIN_IDS")),
        support_url=normalize_public_url(os.getenv("SUPPORT_URL", "https://t.me/your_support_username")),
        public_offer_url=normalize_public_url(os.getenv("PUBLIC_OFFER_URL", "https://example.com/oferta")),
        database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/storage/bot.db").strip(),
        google_sheet_id=_require_env("GOOGLE_SHEET_ID"),
        google_service_account_file=_optional_env("GOOGLE_SERVICE_ACCOUNT_FILE"),
        google_service_account_json=_optional_env("GOOGLE_SERVICE_ACCOUNT_JSON"),
        google_service_account_json_b64=_optional_env("GOOGLE_SERVICE_ACCOUNT_JSON_B64"),
        google_orders_worksheet=os.getenv("GOOGLE_ORDERS_WORKSHEET", "orders").strip() or "orders",
        chatgpt_stock_csv_url=_optional_env("CHATGPT_STOCK_CSV_URL"),
        chatgpt_stock_csv_path=_optional_env("CHATGPT_STOCK_CSV_PATH"),
        chatgpt_stock_reserve_minutes=_parse_int(os.getenv("CHATGPT_STOCK_RESERVE_MINUTES"), 20),
        yookassa_shop_id=_require_env("YOOKASSA_SHOP_ID"),
        yookassa_secret_key=_require_env("YOOKASSA_SECRET_KEY"),
        yookassa_return_url=_require_env("YOOKASSA_RETURN_URL"),
        yookassa_api_base=os.getenv("YOOKASSA_API_BASE", "https://api.yookassa.ru/v3").strip(),
        yookassa_vat_code=_parse_int(os.getenv("YOOKASSA_VAT_CODE"), 1),
        yookassa_tax_system_code=int(tax_system_raw) if tax_system_raw else None,
    )
