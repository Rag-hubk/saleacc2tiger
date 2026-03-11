from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import uuid4

import aiohttp

from saleacc_bot.config import Settings
from saleacc_bot.models import Order


@dataclass(frozen=True)
class YooKassaPayment:
    payment_id: str
    status: str
    confirmation_url: str | None
    metadata: dict[str, str]


class YooKassaClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def create_payment(self, *, order: Order) -> YooKassaPayment:
        payload = {
            "amount": {
                "value": _format_rub_amount(order.total_price),
                "currency": "RUB",
            },
            "capture": True,
            "confirmation": {
                "type": "redirect",
                "return_url": self._settings.yookassa_return_url,
            },
            "description": f"{order.product_title} через Telegram-бот",
            "metadata": {
                "order_id": order.id,
                "telegram_user_id": str(order.tg_user_id),
                "product_slug": order.product_slug,
            },
            "receipt": _build_receipt(settings=self._settings, order=order),
        }
        data = await self._request("POST", "/payments", json=payload, idempotence_key=str(uuid4()))
        return _parse_payment(data)

    async def get_payment(self, payment_id: str) -> YooKassaPayment:
        data = await self._request("GET", f"/payments/{payment_id}")
        return _parse_payment(data)

    async def cancel_payment(self, payment_id: str) -> YooKassaPayment:
        data = await self._request("POST", f"/payments/{payment_id}/cancel", idempotence_key=str(uuid4()))
        return _parse_payment(data)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        idempotence_key: str | None = None,
    ) -> dict[str, Any]:
        url = f"{self._settings.yookassa_api_base.rstrip('/')}{path}"
        headers = {"Content-Type": "application/json"}
        if idempotence_key:
            headers["Idempotence-Key"] = idempotence_key

        auth = aiohttp.BasicAuth(self._settings.yookassa_shop_id, self._settings.yookassa_secret_key)
        async with aiohttp.ClientSession(auth=auth) as session:
            async with session.request(method, url, json=json, headers=headers, timeout=20) as response:
                payload = await response.json()
                if response.status >= 400:
                    description = payload.get("description") if isinstance(payload, dict) else str(payload)
                    raise RuntimeError(f"YooKassa API error: {response.status} {description}")
        if not isinstance(payload, dict):
            raise RuntimeError("YooKassa API returned non-object payload")
        return payload


def _build_receipt(*, settings: Settings, order: Order) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "customer": {"email": order.customer_email},
        "items": [
            {
                "description": order.product_title[:128],
                "quantity": "1.00",
                "amount": {
                    "value": _format_rub_amount(order.total_price),
                    "currency": "RUB",
                },
                "vat_code": settings.yookassa_vat_code,
                "payment_mode": "full_payment",
                "payment_subject": "service",
            }
        ],
    }
    if settings.yookassa_tax_system_code is not None:
        receipt["tax_system_code"] = settings.yookassa_tax_system_code
    return receipt


def _parse_payment(data: dict[str, Any]) -> YooKassaPayment:
    payment_id = str(data.get("id") or "")
    if not payment_id:
        raise RuntimeError("YooKassa response does not contain payment id")
    confirmation = data.get("confirmation")
    confirmation_url = None
    if isinstance(confirmation, dict):
        raw_url = confirmation.get("confirmation_url")
        if raw_url is not None:
            confirmation_url = str(raw_url)
    raw_metadata = data.get("metadata")
    metadata: dict[str, str] = {}
    if isinstance(raw_metadata, dict):
        metadata = {str(key): str(value) for key, value in raw_metadata.items()}
    return YooKassaPayment(
        payment_id=payment_id,
        status=str(data.get("status") or ""),
        confirmation_url=confirmation_url,
        metadata=metadata,
    )


def _format_rub_amount(kopecks: int) -> str:
    rubles = (Decimal(kopecks) / Decimal(100)).quantize(Decimal("0.00"), rounding=ROUND_HALF_UP)
    return format(rubles, "f")
