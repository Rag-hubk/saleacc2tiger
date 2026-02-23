from __future__ import annotations

import asyncio
import time
from functools import lru_cache
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from saleacc_bot.config import get_settings
from saleacc_bot.models import Product
from saleacc_bot.services.sheets_store import SheetsStore

_STOCK_CACHE_TTL_SECONDS = 5.0
_stock_cache_lock = asyncio.Lock()
_stock_cache_ts: float = 0.0
_stock_cache_by_slug: dict[str, int] = {}


@lru_cache(maxsize=1)
def get_sheets_store() -> SheetsStore:
    return SheetsStore(get_settings())


async def invalidate_stock_cache() -> None:
    global _stock_cache_ts, _stock_cache_by_slug
    async with _stock_cache_lock:
        _stock_cache_ts = 0.0
        _stock_cache_by_slug = {}


async def _get_cached_stock_by_slug(product_slugs: list[str]) -> dict[str, int]:
    global _stock_cache_ts, _stock_cache_by_slug
    slugs = list(dict.fromkeys(product_slugs))
    if not slugs:
        return {}

    now = time.monotonic()
    async with _stock_cache_lock:
        cache_ok = now - _stock_cache_ts <= _STOCK_CACHE_TTL_SECONDS
        if cache_ok and all(slug in _stock_cache_by_slug for slug in slugs):
            return {slug: _stock_cache_by_slug.get(slug, 0) for slug in slugs}

    fresh = await get_sheets_store().get_stock_counts(slugs)

    async with _stock_cache_lock:
        _stock_cache_by_slug = dict(fresh)
        _stock_cache_ts = time.monotonic()
    return fresh


async def get_stock_map(session: AsyncSession, product_ids: Sequence[int]) -> dict[int, int]:
    if not product_ids:
        return {}

    products = list(
        await session.scalars(
            select(Product).where(Product.id.in_(product_ids), Product.is_active.is_(True))
        )
    )
    if not products:
        return {pid: 0 for pid in product_ids}

    by_slug = await _get_cached_stock_by_slug([p.slug for p in products])
    by_id = {product.id: by_slug.get(product.slug, 0) for product in products}

    for product_id in product_ids:
        by_id.setdefault(product_id, 0)
    return by_id


async def list_recent_sales(limit: int = 15) -> list[dict[str, str]]:
    return await get_sheets_store().list_recent_sales(limit=limit)


async def get_inventory_summary_by_slug(
    product_slugs: Sequence[str],
) -> dict[str, dict[str, int]]:
    return await get_sheets_store().get_inventory_summary(list(product_slugs))
