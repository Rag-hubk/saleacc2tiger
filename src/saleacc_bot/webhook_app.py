from __future__ import annotations

import hashlib
import hmac
import json
import asyncio
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ValidationError

from saleacc_bot.config import get_settings
from saleacc_bot.db import get_session, init_db
from saleacc_bot.services.cryptobot import (
    extract_invoice_id_from_update,
    extract_order_id_from_update,
    verify_cryptobot_signature,
)
from saleacc_bot.services.inventory import get_sheets_store
from saleacc_bot.models import OrderStatus
from saleacc_bot.services.orders import (
    deliver_order_csv,
    find_pending_fiat_order_for_tribute,
    get_order,
    mark_order_paid,
)
from saleacc_bot.ui import main_menu_payload

app = FastAPI(title="saleacc payment webhooks")
settings = get_settings()
_cryptobot_order_locks: dict[str, asyncio.Lock] = {}


class TributeEvent(BaseModel):
    order_id: str
    status: str
    payment_id: str | None = None


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _get_order_lock(order_id: str) -> asyncio.Lock:
    lock = _cryptobot_order_locks.get(order_id)
    if lock is None:
        lock = asyncio.Lock()
        _cryptobot_order_locks[order_id] = lock
    return lock


def _verify_tribute_signature(body: bytes, signature: str | None) -> bool:
    secret = settings.tribute_webhook_secret
    if not secret:
        return True
    if not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _notify_user_delivery(*, bot: Bot, tg_user_id: int, order_id: str, csv_path: str | None) -> None:
    if csv_path:
        sent = await bot.send_document(
            chat_id=tg_user_id,
            document=FSInputFile(csv_path),
            caption=f"Заказ {order_id[:8]} оплачен и выдан.",
        )
        try:
            await bot.pin_chat_message(
                chat_id=tg_user_id,
                message_id=sent.message_id,
                disable_notification=True,
            )
        except TelegramBadRequest:
            pass
        main_text, main_kb = main_menu_payload(settings, tg_user_id)
        await bot.send_message(chat_id=tg_user_id, text=main_text, reply_markup=main_kb, parse_mode="HTML")
    else:
        await bot.send_message(
            chat_id=tg_user_id,
            text=f"Заказ {order_id[:8]} оплачен. Напишите в поддержку для выдачи.",
        )


@app.on_event("startup")
async def on_startup() -> None:
    await init_db()
    await get_sheets_store().ensure_schema()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhooks/tribute")
async def tribute_webhook(
    request: Request,
    trbt_signature: str | None = Header(default=None, alias="trbt-signature"),
    x_tribute_signature: str | None = Header(default=None),
) -> dict[str, str]:
    body = await request.body()
    signature = trbt_signature or x_tribute_signature
    if not _verify_tribute_signature(body, signature):
        raise HTTPException(status_code=401, detail="invalid signature")

    try:
        incoming: dict[str, Any] = json.loads(body.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"invalid json: {exc}") from exc

    order_id: str | None = None
    provider_charge_id: str | None = None
    telegram_user_id: int | None = None
    amount_cents: int | None = None

    # Legacy format.
    if "order_id" in incoming:
        try:
            event = TributeEvent.model_validate(incoming)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if event.status.lower() not in {"paid", "succeeded"}:
            return {"result": "ignored"}
        order_id = event.order_id
        provider_charge_id = event.payment_id or "tribute-webhook"
    else:
        # Tribute native webhook format for payments.
        event_name = str(incoming.get("name") or "").lower()
        payload = incoming.get("payload")
        paid_events = {
            "new_digital_product",
            "physical_order_created",
            "new_donation",
            "recurrent_donation",
            "new_subscription",
            "renewed_subscription",
        }
        if event_name not in paid_events or not isinstance(payload, dict):
            return {"result": "ignored"}
        telegram_user_id = _to_int(payload.get("telegram_user_id"))
        if telegram_user_id is None:
            return {"result": "ignored"}
        amount_cents = _to_int(payload.get("amount")) or _to_int(payload.get("total"))
        provider_charge_id = str(
            payload.get("purchase_id")
            or payload.get("transaction_id")
            or payload.get("order_id")
            or payload.get("donation_request_id")
            or payload.get("period_id")
            or payload.get("subscription_id")
            or "tribute-webhook"
        )

    async with get_session() as session:
        if order_id is None:
            pending = await find_pending_fiat_order_for_tribute(
                session,
                tg_user_id=telegram_user_id,  # type: ignore[arg-type]
                amount_cents=amount_cents,
            )
            if pending is None:
                raise HTTPException(status_code=404, detail="pending fiat order not found")
            order_id = pending.id

        order = await mark_order_paid(
            session,
            order_id=order_id,
            provider_charge_id=provider_charge_id,
            telegram_payment_charge_id=None,
        )
        if order is None:
            raise HTTPException(status_code=404, detail="order not found or invalid state")

        csv_path = await deliver_order_csv(
            session,
            order_id=order.id,
            export_dir=settings.export_dir,
        )

    bot = Bot(token=settings.bot_token)
    try:
        await _notify_user_delivery(
            bot=bot,
            tg_user_id=order.tg_user_id,
            order_id=order.id,
            csv_path=str(csv_path) if csv_path else None,
        )
    finally:
        await bot.session.close()

    return {"result": "ok"}


@app.post("/webhooks/cryptobot")
async def cryptobot_webhook(
    request: Request,
    crypto_pay_api_signature: str | None = Header(default=None, alias="crypto-pay-api-signature"),
) -> dict[str, str]:
    if not settings.cryptobot_api_token:
        raise HTTPException(status_code=503, detail="cryptobot token is not configured")

    raw_body = await request.body()
    if not verify_cryptobot_signature(
        token=settings.cryptobot_api_token,
        signature=crypto_pay_api_signature,
        raw_body=raw_body,
    ):
        raise HTTPException(status_code=401, detail="invalid signature")
    payload: dict[str, Any] = await request.json()

    order_id = extract_order_id_from_update(payload)
    if not order_id:
        return {"result": "ignored"}

    invoice_id = extract_invoice_id_from_update(payload)
    async with _get_order_lock(order_id):
        async with get_session() as session:
            existing = await get_order(session, order_id)
            if existing is None:
                raise HTTPException(status_code=404, detail="order not found")

            # Crypto webhook can be retried; do not send delivery twice.
            if existing.status == OrderStatus.DELIVERED:
                return {"result": "ok"}

            order = await mark_order_paid(
                session,
                order_id=order_id,
                provider_charge_id=invoice_id,
                telegram_payment_charge_id=None,
            )
            if order is None:
                raise HTTPException(status_code=404, detail="order not found or invalid state")

            csv_path = await deliver_order_csv(
                session,
                order_id=order.id,
                export_dir=settings.export_dir,
            )

        bot = Bot(token=settings.bot_token)
        try:
            await _notify_user_delivery(
                bot=bot,
                tg_user_id=order.tg_user_id,
                order_id=order.id,
                csv_path=str(csv_path) if csv_path else None,
            )
        finally:
            await bot.session.close()

    return {"result": "ok"}
