from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from saleacc_bot.config import Settings
from saleacc_bot.models import Order
from saleacc_bot.services.catalog import get_product_category
from saleacc_bot.services.sheets_store import get_sheets_store

CHATGPT_STOCK_POOL = "chatgpt"


@dataclass(frozen=True)
class DeliveryAccount:
    item_id: str
    access_login: str
    access_secret: str
    note: str
    reserved_until: datetime | None = None


def order_needs_auto_delivery(order: Order) -> bool:
    return get_product_category(order.product_slug) == CHATGPT_STOCK_POOL


async def cleanup_expired_reservations(session: AsyncSession) -> None:
    expired_order_ids = await get_sheets_store().cleanup_expired_inventory_reservations()
    if not expired_order_ids:
        return

    orders = await session.scalars(select(Order).where(Order.id.in_(expired_order_ids), Order.delivered_at.is_(None)))
    for order in orders:
        order.assigned_stock_item_id = None
        order.reserved_until = None
    await session.commit()


async def reserve_chatgpt_account(session: AsyncSession, settings: Settings, order: Order) -> DeliveryAccount | None:
    await cleanup_expired_reservations(session)
    row = await get_sheets_store().reserve_inventory_item(
        order_id=order.id,
        product_key=order.product_slug,
        product_title=order.product_title,
        reserve_minutes=settings.chatgpt_stock_reserve_minutes,
    )
    if row is None:
        return None

    reserved_until = _parse_dt(row.get("reserved_until", ""))
    order.assigned_stock_item_id = row.get("inventory_key") or None
    order.reserved_until = reserved_until
    await session.commit()
    return _delivery_account_from_row(row)


async def release_chatgpt_reservation(session: AsyncSession, order: Order) -> None:
    await get_sheets_store().release_inventory_reservation(order_id=order.id)
    if order.delivered_at is None:
        order.assigned_stock_item_id = None
    order.reserved_until = None
    await session.commit()


async def claim_chatgpt_account(session: AsyncSession, settings: Settings, order: Order) -> DeliveryAccount | None:
    await cleanup_expired_reservations(session)
    row = await get_sheets_store().claim_inventory_item(
        order_id=order.id,
        product_key=order.product_slug,
        product_title=order.product_title,
        reserve_minutes=settings.chatgpt_stock_reserve_minutes,
    )
    if row is None:
        return None

    now = datetime.now(timezone.utc)
    order.assigned_stock_item_id = row.get("inventory_key") or None
    order.reserved_until = None
    order.delivered_at = now
    await session.commit()
    return _delivery_account_from_row(row)


def _delivery_account_from_row(row: dict[str, str]) -> DeliveryAccount:
    return DeliveryAccount(
        item_id=(row.get("inventory_key") or "").strip(),
        access_login=(row.get("access_login") or "").strip(),
        access_secret=(row.get("access_secret") or "").strip(),
        note=(row.get("note") or "").strip(),
        reserved_until=_parse_dt(row.get("reserved_until", "")),
    )


def _parse_dt(raw: str) -> datetime | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
