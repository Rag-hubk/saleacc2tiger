from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: list[int]
    support_url: str

    database_url: str

    tribute_base_url: str
    tribute_enabled: bool
    tribute_webhook_secret: str
    tribute_link_gpt_pro_1m: str
    tribute_link_gpt_pro_3m: str
    tribute_link_lovable_100: str
    tribute_link_lovable_200: str
    tribute_link_lovable_300: str
    tribute_link_replit_core: str
    tribute_link_replit_team: str

    cryptobot_enabled: bool
    cryptobot_api_base: str
    cryptobot_api_token: str
    cryptobot_asset: str
    crypto_buy_url: str

    export_dir: str
    google_sheet_id: str
    google_service_account_file: str
    google_inventory_worksheet: str
    google_sales_worksheet: str


def _parse_admin_ids(value: str | None) -> list[int]:
    if not value:
        return []
    result: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        result.append(int(part))
    return result


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value == "..." or value.startswith("replace_"):
        raise RuntimeError(f"Environment variable {name} is required")
    return value


def _opt_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value in {"...", "replace_me", "replace_with_value"}:
        return ""
    return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        bot_token=_require_env("TELEGRAM_BOT_TOKEN"),
        admin_ids=_parse_admin_ids(os.getenv("TELEGRAM_ADMIN_IDS")),
        support_url=os.getenv("SUPPORT_URL", "https://t.me/your_support_username"),
        database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/storage/bot.db"),
        tribute_base_url=os.getenv("TRIBUTE_BASE_URL", "https://tribute.tg/pay"),
        tribute_enabled=_parse_bool(os.getenv("TRIBUTE_ENABLED"), True),
        tribute_webhook_secret=os.getenv("TRIBUTE_WEBHOOK_SECRET", ""),
        tribute_link_gpt_pro_1m=_opt_env("TRIBUTE_LINK_GPT_PRO_1M"),
        tribute_link_gpt_pro_3m=_opt_env("TRIBUTE_LINK_GPT_PRO_3M"),
        tribute_link_lovable_100=_opt_env("TRIBUTE_LINK_LOVABLE_100"),
        tribute_link_lovable_200=_opt_env("TRIBUTE_LINK_LOVABLE_200"),
        tribute_link_lovable_300=_opt_env("TRIBUTE_LINK_LOVABLE_300"),
        tribute_link_replit_core=_opt_env("TRIBUTE_LINK_REPLIT_CORE"),
        tribute_link_replit_team=_opt_env("TRIBUTE_LINK_REPLIT_TEAM"),
        cryptobot_enabled=_parse_bool(os.getenv("CRYPTOBOT_ENABLED"), True),
        cryptobot_api_base=os.getenv("CRYPTOBOT_API_BASE", "https://pay.crypt.bot/api"),
        cryptobot_api_token=_opt_env("CRYPTOBOT_API_TOKEN"),
        cryptobot_asset=os.getenv("CRYPTOBOT_ASSET", "USDT"),
        crypto_buy_url=os.getenv("CRYPTO_BUY_URL", "https://t.me/send?start=r-t3x5q-market").strip(),
        export_dir=os.getenv("EXPORT_DIR", "data/storage/exports"),
        google_sheet_id=_require_env("GOOGLE_SHEET_ID"),
        google_service_account_file=_require_env("GOOGLE_SERVICE_ACCOUNT_FILE"),
        google_inventory_worksheet=os.getenv("GOOGLE_INVENTORY_WORKSHEET", "inventory"),
        google_sales_worksheet=os.getenv("GOOGLE_SALES_WORKSHEET", "sales"),
    )
