from __future__ import annotations

import asyncio
from typing import Any

from aiogram import Bot
from fastapi import FastAPI, HTTPException, Request

from saleacc_bot.config import get_settings
from saleacc_bot.db import get_session, init_db
from saleacc_bot.services.catalog import seed_default_products
from saleacc_bot.services.notifications import notify_order_paid
from saleacc_bot.services.orders import (
    ORDER_STATUS_PAID,
    get_order,
    get_order_by_payment_id,
    mark_order_cancelled,
    mark_order_paid,
)
from saleacc_bot.services.sheets_store import get_sheets_store
from saleacc_bot.services.stock import claim_chatgpt_account, cleanup_expired_reservations, order_needs_auto_delivery, release_chatgpt_reservation
from saleacc_bot.services.yookassa import YooKassaClient

app = FastAPI(title="saleacc yookassa webhooks")
settings = get_settings()
yookassa_client = YooKassaClient(settings)
_payment_locks: dict[str, asyncio.Lock] = {}


def _payment_lock(payment_id: str) -> asyncio.Lock:
    lock = _payment_locks.get(payment_id)
    if lock is None:
        lock = asyncio.Lock()
        _payment_locks[payment_id] = lock
    return lock


@app.on_event("startup")
async def on_startup() -> None:
    await init_db()
    async with get_session() as session:
        await seed_default_products(session)
        await cleanup_expired_reservations(session)
    await get_sheets_store().ensure_schema()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhooks/yookassa")
async def yookassa_webhook(request: Request) -> dict[str, str]:
    payload: dict[str, Any] = await request.json()
    event = str(payload.get("event") or "")
    obj = payload.get("object")
    if not isinstance(obj, dict):
        return {"result": "ignored"}

    payment_id = str(obj.get("id") or "")
    if not payment_id:
        raise HTTPException(status_code=422, detail="payment id is missing")

    async with _payment_lock(payment_id):
        payment = await yookassa_client.get_payment(payment_id)
        order_id = payment.metadata.get("order_id")

        async with get_session() as session:
            order = None
            if order_id:
                order = await get_order(session, order_id)
            if order is None:
                order = await get_order_by_payment_id(session, payment_id)
            if order is None:
                raise HTTPException(status_code=404, detail="order not found")

            if payment.status == "succeeded":
                already_paid = order.status == ORDER_STATUS_PAID
                order = await mark_order_paid(
                    session,
                    order_id=order.id,
                    provider_payment_id=payment.payment_id,
                    provider_status=payment.status,
                )
                if order is None:
                    raise HTTPException(status_code=500, detail="cannot update order")
                delivered_account = None
                if order_needs_auto_delivery(order):
                    try:
                        delivered_account = await claim_chatgpt_account(session, settings, order)
                    except RuntimeError:
                        delivered_account = None
                await get_sheets_store().upsert_order(order)
                if not already_paid:
                    bot = Bot(token=settings.bot_token)
                    try:
                        await notify_order_paid(bot, settings, order, stock_account=delivered_account)
                    finally:
                        await bot.session.close()
                return {"result": "ok"}

            if payment.status == "canceled" or event == "payment.canceled":
                order = await mark_order_cancelled(
                    session,
                    order_id=order.id,
                    provider_status=payment.status or "canceled",
                    reason="YooKassa canceled payment",
                )
                if order is not None:
                    if order_needs_auto_delivery(order):
                        await release_chatgpt_reservation(session, order)
                    await get_sheets_store().upsert_order(order)
                return {"result": "ok"}

            order.provider_status = payment.status
            if payment.confirmation_url:
                order.payment_confirmation_url = payment.confirmation_url
            await session.commit()
            await get_sheets_store().upsert_order(order)

    return {"result": "ok"}
