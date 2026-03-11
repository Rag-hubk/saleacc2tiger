from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from saleacc_bot.models import Product


@dataclass(frozen=True)
class ProductSpec:
    slug: str
    title: str
    description: str
    price_kopecks: int
    sort_order: int
    features: tuple[str, ...]


PRODUCT_SPECS: tuple[ProductSpec, ...] = (
    ProductSpec(
        slug="gpt-plus-1m",
        title="ChatGPT Plus · 1 месяц",
        description="Базовый платный тариф ChatGPT для ежедневного использования.",
        price_kopecks=49900,
        sort_order=10,
        features=(
            "Доступ к ChatGPT Plus",
            "Codex для рабочих сценариев и генерации кода",
            "Работа с файлами, изображениями и документами",
            "Расширенный голосовой режим",
            "Доступ к Sora с лимитами тарифа Plus",
            "Приоритетнее обычного бесплатного плана",
        ),
    ),
    ProductSpec(
        slug="gpt-pro-1m",
        title="ChatGPT Pro · 1 месяц",
        description="Максимальный тариф OpenAI на 1 месяц с повышенными лимитами и расширенным доступом к инструментам.",
        price_kopecks=499000,
        sort_order=20,
        features=(
            "Максимальные лимиты на модели и рабочие инструменты",
            "Усиленный сценарий работы с Codex",
            "Больше ресурса под Sora и исследовательские задачи",
            "Приоритетный доступ к новым возможностям OpenAI",
            "Формат на 1 месяц для быстрого старта",
        ),
    ),
    ProductSpec(
        slug="gpt-pro-3m",
        title="ChatGPT Pro · 3 месяца",
        description="Максимальный тариф OpenAI на 3 месяца с повышенными лимитами и расширенным доступом к инструментам.",
        price_kopecks=999000,
        sort_order=30,
        features=(
            "Максимальные лимиты на модели и рабочие инструменты",
            "Усиленный сценарий работы с Codex",
            "Больше ресурса под Sora и исследовательские задачи",
            "Приоритетный доступ к новым возможностям OpenAI",
            "Формат на 3 месяца без ежемесячного продления",
        ),
    ),
    ProductSpec(
        slug="gpt-pro-6m",
        title="ChatGPT Pro · 6 месяцев",
        description="Максимальный тариф OpenAI на 6 месяцев с повышенными лимитами и расширенным доступом к инструментам.",
        price_kopecks=1399000,
        sort_order=40,
        features=(
            "Максимальные лимиты на модели и рабочие инструменты",
            "Усиленный сценарий работы с Codex",
            "Больше ресурса под Sora и исследовательские задачи",
            "Приоритетный доступ к новым возможностям OpenAI",
            "Формат на 6 месяцев для долгой непрерывной работы",
        ),
    ),
)


def get_product_spec(slug: str) -> ProductSpec | None:
    for spec in PRODUCT_SPECS:
        if spec.slug == slug:
            return spec
    return None


async def seed_default_products(session: AsyncSession) -> None:
    existing_products = list(await session.scalars(select(Product)))
    by_slug = {product.slug: product for product in existing_products}
    active_slugs = {spec.slug for spec in PRODUCT_SPECS}

    for product in existing_products:
        if product.slug not in active_slugs:
            product.is_active = False

    for spec in PRODUCT_SPECS:
        product = by_slug.get(spec.slug)
        if product is None:
            session.add(
                Product(
                    slug=spec.slug,
                    title=spec.title,
                    description=spec.description,
                    price_kopecks=spec.price_kopecks,
                    sort_order=spec.sort_order,
                    is_active=True,
                )
            )
            continue

        product.title = spec.title
        product.description = spec.description
        product.price_kopecks = spec.price_kopecks
        product.sort_order = spec.sort_order
        product.is_active = True

    await session.commit()


async def list_active_products(session: AsyncSession) -> Sequence[Product]:
    result = await session.scalars(
        select(Product).where(Product.is_active.is_(True)).order_by(Product.sort_order.asc(), Product.id.asc())
    )
    return list(result)


async def get_product_by_id(session: AsyncSession, product_id: int) -> Product | None:
    return await session.get(Product, product_id)


async def get_product_by_slug(session: AsyncSession, slug: str) -> Product | None:
    return await session.scalar(select(Product).where(Product.slug == slug, Product.is_active.is_(True)))
