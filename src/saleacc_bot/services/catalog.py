from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from saleacc_bot.models import Product


@dataclass(frozen=True)
class ProductSpec:
    slug: str
    category: str
    title: str
    button_title: str
    description: str
    price_kopecks: int
    official_price_kopecks: int
    sort_order: int
    features: tuple[str, ...]
    audience: str


PRODUCT_SPECS: tuple[ProductSpec, ...] = (
    ProductSpec(
        slug="gpt-plus-1m",
        category="chatgpt",
        title="ChatGPT Plus",
        button_title="💚 ChatGPT Plus — 499₽/мес",
        description="ChatGPT Plus для ежедневной работы, учебы и регулярных задач.",
        price_kopecks=49900,
        official_price_kopecks=158000,
        sort_order=10,
        features=(
            "GPT-5 с продвинутым мышлением",
            "Генерация картинок (DALL-E)",
            "Создание видео (Sora, 720p)",
            "Deep Research — глубокий анализ тем",
            "Codex — AI-помощник для кода",
            "До 160 сообщений / 3 часа",
        ),
        audience="Для кого: фрилансеры, студенты, маркетологи, все кому нужен мощный AI каждый день",
    ),
    ProductSpec(
        slug="gpt-pro-1m",
        category="chatgpt",
        title="ChatGPT Pro",
        button_title="💛 ChatGPT Pro — 4 990₽/мес",
        description="Максимальный тариф ChatGPT для высокой рабочей нагрузки.",
        price_kopecks=499000,
        official_price_kopecks=1580000,
        sort_order=20,
        features=(
            "Безлимитные сообщения и загрузки",
            "Pro-режим мышления GPT-5 (думает дольше = отвечает точнее)",
            "Максимальный Deep Research и Agent Mode",
            "Sora без ограничений",
            "Расширенный Codex-агент",
            "Приоритет во всём",
            "VPN в подарок — только для покупателей ChatGPT Pro",
        ),
        audience="Для кого: разработчики, аналитики, предприниматели, кто работает с AI на максимум",
    ),
    ProductSpec(
        slug="gemini-ultra-1m",
        category="gemini",
        title="Google AI Ultra",
        button_title="💙 Google AI Ultra — 7 990₽/мес",
        description="Максимальная подписка Google AI для видео, изображений, исследований и AI-агентов.",
        price_kopecks=799000,
        official_price_kopecks=1975000,
        sort_order=40,
        features=(
            "Gemini 3.1 Pro — самая умная модель Google",
            "Nano Banana Pro — генерация и редактирование изображений нового уровня",
            "Veo 3.1 — создание видео кинематографического качества",
            "Flow — AI-инструмент для монтажа фильмов и сцен",
            "Deep Research — автоматические исследования по любой теме",
            "Agent Mode — AI сам выполняет задачи за тебя",
            "25 000 AI-кредитов в месяц",
            "30 ТБ облачного хранилища (Google Drive, Gmail, Photos)",
            "YouTube Premium включён",
            "NotebookLM Pro — AI-помощник для учёбы и работы",
        ),
        audience="Для кого: контент-мейкеры, видеографы, дизайнеры, исследователи, все кто хочет максимум от Google AI",
    ),
)


def get_product_spec(slug: str) -> ProductSpec | None:
    for spec in PRODUCT_SPECS:
        if spec.slug == slug:
            return spec
    return None


def get_product_category(slug: str) -> str | None:
    spec = get_product_spec(slug)
    return spec.category if spec is not None else None


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
