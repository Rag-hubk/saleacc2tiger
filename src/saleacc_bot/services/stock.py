from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import aiohttp
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from saleacc_bot.config import Settings
from saleacc_bot.models import Order, StockAccount
from saleacc_bot.services.catalog import get_product_category

CHATGPT_STOCK_POOL = "chatgpt"


@dataclass(frozen=True)
class StockRow:
    item_id: str
    access_login: str
    access_secret: str
    note: str


def order_needs_auto_delivery(order: Order) -> bool:
    return get_product_category(order.product_slug) == CHATGPT_STOCK_POOL


async def sync_chatgpt_stock(session: AsyncSession, settings: Settings) -> int:
    rows = await _load_chatgpt_stock_rows(settings)
    seen: set[str] = set()

    existing = await session.scalars(select(StockAccount).where(StockAccount.pool == CHATGPT_STOCK_POOL))
    by_item_id = {item.item_id: item for item in existing}

    for row in rows:
        seen.add(row.item_id)
        item = by_item_id.get(row.item_id)
        if item is None:
            session.add(
                StockAccount(
                    pool=CHATGPT_STOCK_POOL,
                    item_id=row.item_id,
                    access_login=row.access_login,
                    access_secret=row.access_secret,
                    note=row.note or None,
                    is_active=True,
                )
            )
            continue

        item.access_login = row.access_login
        item.access_secret = row.access_secret
        item.note = row.note or None
        item.is_active = True

    for item in by_item_id.values():
        if item.item_id not in seen:
            item.is_active = False

    await session.commit()
    return len(seen)


async def cleanup_expired_reservations(session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    expired_items = await session.scalars(
        select(StockAccount).where(
            StockAccount.pool == CHATGPT_STOCK_POOL,
            StockAccount.delivered_at.is_(None),
            StockAccount.reserved_until.is_not(None),
            StockAccount.reserved_until < now,
        )
    )
    expired_order_ids: list[str] = []
    for item in expired_items:
        if item.reserved_for_order_id:
            expired_order_ids.append(item.reserved_for_order_id)
        item.reserved_for_order_id = None
        item.reserved_until = None

    if expired_order_ids:
        orders = await session.scalars(select(Order).where(Order.id.in_(expired_order_ids), Order.delivered_at.is_(None)))
        for order in orders:
            order.assigned_stock_item_id = None
            order.reserved_until = None

    await session.commit()


async def reserve_chatgpt_account(session: AsyncSession, settings: Settings, order: Order) -> StockAccount | None:
    await cleanup_expired_reservations(session)
    await sync_chatgpt_stock(session, settings)

    existing = await get_reserved_chatgpt_account_for_order(session, order.id)
    if existing is not None:
        return existing

    now = datetime.now(timezone.utc)
    reserve_until = now + timedelta(minutes=settings.chatgpt_stock_reserve_minutes)
    item = await session.scalar(
        select(StockAccount)
        .where(
            StockAccount.pool == CHATGPT_STOCK_POOL,
            StockAccount.is_active.is_(True),
            StockAccount.delivered_at.is_(None),
            or_(StockAccount.reserved_until.is_(None), StockAccount.reserved_until < now),
        )
        .order_by(StockAccount.id.asc())
        .limit(1)
    )
    if item is None:
        return None

    item.reserved_for_order_id = order.id
    item.reserved_until = reserve_until
    order.assigned_stock_item_id = item.item_id
    order.reserved_until = reserve_until
    await session.commit()
    await session.refresh(item)
    return item


async def get_reserved_chatgpt_account_for_order(session: AsyncSession, order_id: str) -> StockAccount | None:
    return await session.scalar(
        select(StockAccount).where(
            StockAccount.pool == CHATGPT_STOCK_POOL,
            StockAccount.reserved_for_order_id == order_id,
            StockAccount.delivered_at.is_(None),
        )
    )


async def release_chatgpt_reservation(session: AsyncSession, order: Order) -> None:
    item = await get_reserved_chatgpt_account_for_order(session, order.id)
    if item is not None:
        item.reserved_for_order_id = None
        item.reserved_until = None
    if order.delivered_at is None:
        order.assigned_stock_item_id = None
    order.reserved_until = None
    await session.commit()


async def claim_chatgpt_account(session: AsyncSession, settings: Settings, order: Order) -> StockAccount | None:
    await cleanup_expired_reservations(session)
    item = await get_reserved_chatgpt_account_for_order(session, order.id)
    if item is None:
        item = await reserve_chatgpt_account(session, settings, order)
        if item is None:
            return None

    now = datetime.now(timezone.utc)
    item.reserved_for_order_id = None
    item.reserved_until = None
    item.delivered_for_order_id = order.id
    item.delivered_at = now
    order.assigned_stock_item_id = item.item_id
    order.reserved_until = None
    order.delivered_at = now
    await session.commit()
    await session.refresh(item)
    return item


async def _load_chatgpt_stock_rows(settings: Settings) -> list[StockRow]:
    if settings.chatgpt_stock_csv_url:
        raw_csv = await _load_csv_from_url(settings.chatgpt_stock_csv_url)
        return list(_parse_stock_rows(raw_csv))
    if settings.chatgpt_stock_csv_path:
        raw_csv = Path(settings.chatgpt_stock_csv_path).read_text(encoding="utf-8")
        return list(_parse_stock_rows(raw_csv))
    raise RuntimeError("ChatGPT stock source is not configured. Set CHATGPT_STOCK_CSV_URL or CHATGPT_STOCK_CSV_PATH.")


async def _load_csv_from_url(url: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=20) as response:
            if response.status >= 400:
                raise RuntimeError(f"Failed to load stock CSV: HTTP {response.status}")
            return await response.text(encoding="utf-8")


def _parse_stock_rows(raw_csv: str) -> Iterable[StockRow]:
    reader = csv.DictReader(raw_csv.splitlines())
    required_fields = {"item_id", "access_login", "access_secret"}
    if reader.fieldnames is None or not required_fields.issubset(set(reader.fieldnames)):
        raise RuntimeError("ChatGPT stock CSV must contain item_id, access_login, access_secret columns.")

    for row in reader:
        item_id = str(row.get("item_id") or "").strip()
        access_login = str(row.get("access_login") or "").strip()
        access_secret = str(row.get("access_secret") or "").strip()
        note = str(row.get("note") or "").strip()
        if not item_id or not access_login or not access_secret:
            continue
        yield StockRow(
            item_id=item_id,
            access_login=access_login,
            access_secret=access_secret,
            note=note,
        )
