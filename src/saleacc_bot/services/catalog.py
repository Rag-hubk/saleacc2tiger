from __future__ import annotations

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from saleacc_bot.models import Product

DEFAULT_PRODUCTS = [
    {
        "slug": "gpt-pro-1m",
        "title": "GPT Pro · 1 месяц",
        "description": "GPT Pro, Codex и повышенные лимиты",
        "price_usd_cents": 5000,
        "price_stars": 5000,
    },
    {
        "slug": "gpt-pro-3m",
        "title": "GPT Pro · 3 месяца",
        "description": "GPT Pro, Codex и повышенные лимиты",
        "price_usd_cents": 10000,
        "price_stars": 10000,
    },
    {
        "slug": "gemini-ultra-1m",
        "title": "Gemini AI Ultra · 1 месяц",
        "description": "Gemini AI Ultra + доступ к antigravity",
        "price_usd_cents": 13000,
        "price_stars": 13000,
    },
    {
        "slug": "lovable-100",
        "title": "Lovable AI Pro · 100 токенов",
        "description": "На аккаунте 100 внутренних токенов",
        "price_usd_cents": 1500,
        "price_stars": 1500,
    },
    {
        "slug": "lovable-200",
        "title": "Lovable AI Pro · 200 токенов",
        "description": "На аккаунте 200 внутренних токенов",
        "price_usd_cents": 2500,
        "price_stars": 2500,
    },
    {
        "slug": "lovable-300",
        "title": "Lovable AI Pro · 300 токенов",
        "description": "На аккаунте 300 внутренних токенов",
        "price_usd_cents": 4500,
        "price_stars": 4500,
    },
    {
        "slug": "replit-core",
        "title": "Replit · Core",
        "description": "Внутренний баланс 50 + 10 бонусных единиц",
        "price_usd_cents": 1500,
        "price_stars": 1500,
    },
    {
        "slug": "replit-team",
        "title": "Replit · Team",
        "description": "Внутренний баланс 120 единиц",
        "price_usd_cents": 4000,
        "price_stars": 4000,
    },
]


async def seed_default_products(session: AsyncSession) -> None:
    existing_products = list(await session.scalars(select(Product)))
    by_slug = {p.slug: p for p in existing_products}
    default_slugs = {item["slug"] for item in DEFAULT_PRODUCTS}

    for product in existing_products:
        if product.slug not in default_slugs:
            product.is_active = False

    for item in DEFAULT_PRODUCTS:
        product = by_slug.get(item["slug"])
        if product is None:
            session.add(Product(**item, is_active=True))
            continue

        product.title = item["title"]
        product.description = item["description"]
        product.price_usd_cents = item["price_usd_cents"]
        product.price_stars = item["price_stars"]
        product.is_active = True

    await session.commit()


async def list_active_products(session: AsyncSession) -> Sequence[Product]:
    result = await session.scalars(select(Product).where(Product.is_active.is_(True)).order_by(Product.id))
    return list(result)


async def get_product_by_id(session: AsyncSession, product_id: int) -> Product | None:
    return await session.get(Product, product_id)
