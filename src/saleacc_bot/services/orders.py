from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from saleacc_bot.models import Order, Product


ORDER_STATUS_PENDING = "pending_payment"
ORDER_STATUS_PAID = "paid"
ORDER_STATUS_CANCELLED = "cancelled"
ORDER_STATUS_FAILED = "failed"


async def create_order(
    session: AsyncSession,
    *,
    user_id: int,
    username: str | None,
    customer_email: str,
    product: Product,
) -> Order:
    order = Order(
        id=str(uuid4()),
        tg_user_id=user_id,
        tg_username=username,
        customer_email=customer_email,
        product_id=product.id,
        product_slug=product.slug,
        product_title=product.title,
        quantity=1,
        payment_method="yookassa",
        currency="RUB",
        unit_price=product.price_kopecks,
        total_price=product.price_kopecks,
        status=ORDER_STATUS_PENDING,
    )
    session.add(order)
    await session.commit()
    return await get_order(session, order.id)  # type: ignore[return-value]


async def attach_provider_payment(
    session: AsyncSession,
    *,
    order_id: str,
    payment_id: str,
    confirmation_url: str,
    provider_status: str,
) -> Order | None:
    order = await get_order(session, order_id)
    if order is None:
        return None
    order.provider_payment_id = payment_id
    order.payment_confirmation_url = confirmation_url
    order.provider_status = provider_status
    await session.commit()
    return order


async def mark_order_paid(
    session: AsyncSession,
    *,
    order_id: str,
    provider_payment_id: str | None,
    provider_status: str,
) -> Order | None:
    order = await get_order(session, order_id)
    if order is None:
        return None
    if order.status == ORDER_STATUS_PAID:
        return order

    order.status = ORDER_STATUS_PAID
    order.provider_status = provider_status
    if provider_payment_id:
        order.provider_payment_id = provider_payment_id
    order.paid_at = datetime.now(timezone.utc)
    order.cancelled_at = None
    order.cancellation_reason = None
    await session.commit()
    return order


async def mark_order_cancelled(
    session: AsyncSession,
    *,
    order_id: str,
    provider_status: str,
    reason: str | None = None,
) -> Order | None:
    order = await get_order(session, order_id)
    if order is None:
        return None
    if order.status == ORDER_STATUS_PAID:
        return order

    order.status = ORDER_STATUS_CANCELLED
    order.provider_status = provider_status
    order.cancelled_at = datetime.now(timezone.utc)
    order.cancellation_reason = reason
    await session.commit()
    return order


async def mark_order_failed(
    session: AsyncSession,
    *,
    order_id: str,
    provider_status: str,
    reason: str | None = None,
) -> Order | None:
    order = await get_order(session, order_id)
    if order is None:
        return None
    if order.status == ORDER_STATUS_PAID:
        return order

    order.status = ORDER_STATUS_FAILED
    order.provider_status = provider_status
    order.cancellation_reason = reason
    await session.commit()
    return order


async def get_order(session: AsyncSession, order_id: str) -> Order | None:
    return await session.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.product))
    )


async def get_order_by_payment_id(session: AsyncSession, payment_id: str) -> Order | None:
    return await session.scalar(
        select(Order)
        .where(Order.provider_payment_id == payment_id)
        .options(selectinload(Order.product))
    )


async def list_user_orders(
    session: AsyncSession,
    *,
    user_id: int,
    limit: int = 10,
) -> Sequence[Order]:
    result = await session.scalars(
        select(Order)
        .where(Order.tg_user_id == user_id)
        .options(selectinload(Order.product))
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    return list(result)


async def list_recent_orders(
    session: AsyncSession,
    *,
    limit: int = 20,
) -> Sequence[Order]:
    result = await session.scalars(
        select(Order)
        .options(selectinload(Order.product))
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    return list(result)


async def get_dashboard_stats(session: AsyncSession) -> dict[str, object]:
    total_orders = int(await session.scalar(select(func.count()).select_from(Order)) or 0)
    paid_orders = int(
        await session.scalar(
            select(func.count()).select_from(Order).where(Order.status == ORDER_STATUS_PAID)
        )
        or 0
    )
    pending_orders = int(
        await session.scalar(
            select(func.count()).select_from(Order).where(Order.status == ORDER_STATUS_PENDING)
        )
        or 0
    )
    paid_revenue_kopecks = int(
        await session.scalar(
            select(func.coalesce(func.sum(Order.total_price), 0)).where(Order.status == ORDER_STATUS_PAID)
        )
        or 0
    )

    by_product_rows = await session.execute(
        select(Order.product_title, func.count(), func.coalesce(func.sum(Order.total_price), 0))
        .where(Order.status == ORDER_STATUS_PAID)
        .group_by(Order.product_title)
        .order_by(Order.product_title.asc())
    )

    return {
        "total_orders": total_orders,
        "paid_orders": paid_orders,
        "pending_orders": pending_orders,
        "paid_revenue_kopecks": paid_revenue_kopecks,
        "by_product": [
            {
                "title": str(row[0]),
                "orders": int(row[1]),
                "revenue_kopecks": int(row[2]),
            }
            for row in by_product_rows.all()
        ],
    }
