from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import aiohttp

from saleacc_bot.config import Settings


@dataclass
class CryptoInvoice:
    invoice_id: str
    pay_url: str


class CryptoBotClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def create_invoice(
        self,
        *,
        order_id: str,
        amount_usd_cents: int,
        product_title: str,
        quantity: int,
    ) -> CryptoInvoice:
        token = self._settings.cryptobot_api_token.strip()
        if not token:
            raise RuntimeError("CRYPTOBOT_API_TOKEN is not configured")

        amount = (Decimal(amount_usd_cents) / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        payload = {
            "asset": self._settings.cryptobot_asset,
            "amount": format(amount, "f"),
            "description": f"{product_title} x{quantity}",
            "payload": f"order:{order_id}",
            "allow_comments": False,
            "allow_anonymous": True,
        }

        url = f"{self._settings.cryptobot_api_base.rstrip('/')}/createInvoice"
        headers = {"Crypto-Pay-API-Token": token}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=20) as response:
                text = await response.text()
                if response.status >= 400:
                    raise RuntimeError(f"Crypto Bot API error: {response.status} {text[:300]}")
                data = json.loads(text)

        if not data.get("ok"):
            raise RuntimeError(f"Crypto Bot createInvoice failed: {data}")

        result = data.get("result") or {}
        pay_url = result.get("pay_url") or result.get("bot_invoice_url") or result.get("mini_app_invoice_url")
        invoice_id = str(result.get("invoice_id") or "")
        if not pay_url or not invoice_id:
            raise RuntimeError("Crypto Bot invoice response is incomplete")

        return CryptoInvoice(invoice_id=invoice_id, pay_url=pay_url)


def verify_cryptobot_signature(*, token: str, signature: str | None, raw_body: bytes) -> bool:
    if not token:
        return False
    if not signature:
        return False

    secret = hashlib.sha256(token.encode("utf-8")).digest()
    expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def extract_order_id_from_update(update: dict[str, Any]) -> str | None:
    update_type = str(update.get("update_type") or "").lower()
    if update_type not in {"invoice_paid", "invoicepartiallypaid"}:
        return None

    payload = update.get("payload")
    if not isinstance(payload, dict):
        return None

    raw_payload = str(payload.get("payload") or "")
    if raw_payload.startswith("order:"):
        return raw_payload.split(":", maxsplit=1)[1]

    return None


def extract_invoice_id_from_update(update: dict[str, Any]) -> str:
    payload = update.get("payload")
    if isinstance(payload, dict):
        value = payload.get("invoice_id")
        if value is not None:
            return str(value)
    return "cryptobot-webhook"
