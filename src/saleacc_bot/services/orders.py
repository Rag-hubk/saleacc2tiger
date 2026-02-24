from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from saleacc_bot.models import Order, OrderStatus, PaymentMethod, Product
from saleacc_bot.services.inventory import get_sheets_store, invalidate_stock_cache

RESERVE_MINUTES = 20


async def cleanup_expired_reservations(
    session: AsyncSession,
    *,
    auto_commit: bool = True,
) -> None:
    expired_order_ids = await get_sheets_store().cleanup_expired_reservations()
    if expired_order_ids:
        await invalidate_stock_cache()

    if expired_order_ids:
        await session.execute(
            update(Order)
            .where(
                Order.id.in_(expired_order_ids),
                Order.status.in_([OrderStatus.CREATED, OrderStatus.PENDING_PAYMENT]),
            )
            .values(status=OrderStatus.CANCELLED)
        )

    stale_threshold = datetime.now(timezone.utc) - timedelta(minutes=RESERVE_MINUTES)
    await session.execute(
        update(Order)
        .where(
            Order.status.in_([OrderStatus.CREATED, OrderStatus.PENDING_PAYMENT]),
            Order.created_at < stale_threshold,
        )
        .values(status=OrderStatus.CANCELLED)
    )

    if auto_commit:
        await session.commit()


async def create_order_with_reservation(
    session: AsyncSession,
    *,
    user_id: int,
    username: str | None,
    product: Product,
    quantity: int,
    payment_method: PaymentMethod,
    unit_price_cents: int | None = None,
) -> Order | None:
    if quantity < 1:
        return None

    await cleanup_expired_reservations(session, auto_commit=False)

    order_id = str(uuid4())
    reserved_rows = await get_sheets_store().reserve_items(
        product_slug=product.slug,
        quantity=quantity,
        buyer_tg_id=user_id,
        order_id=order_id,
        hold_minutes=RESERVE_MINUTES,
    )
    if len(reserved_rows) < quantity:
        await session.rollback()
        return None
    await invalidate_stock_cache()

    unit_price = max(1, unit_price_cents if unit_price_cents is not None else product.price_usd_cents)
    currency = "USDT" if payment_method == PaymentMethod.CRYPTO else "USD"
    order = Order(
        id=order_id,
        tg_user_id=user_id,
        tg_username=username,
        product_id=product.id,
        quantity=quantity,
        payment_method=payment_method,
        currency=currency,
        unit_price=unit_price,
        total_price=unit_price * quantity,
        status=OrderStatus.PENDING_PAYMENT,
    )
    session.add(order)
    await session.commit()

    return await get_order(session, order.id)


async def get_order(session: AsyncSession, order_id: str) -> Order | None:
    return await session.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(
            selectinload(Order.product),
        )
    )


async def mark_order_paid(
    session: AsyncSession,
    *,
    order_id: str,
    provider_charge_id: str | None,
    telegram_payment_charge_id: str | None,
) -> Order | None:
    await cleanup_expired_reservations(session, auto_commit=False)

    order = await get_order(session, order_id)
    if order is None:
        return None

    if order.status in {OrderStatus.PAID, OrderStatus.DELIVERED}:
        return order

    if order.status not in {OrderStatus.CREATED, OrderStatus.PENDING_PAYMENT}:
        return None

    order.status = OrderStatus.PAID
    order.provider_charge_id = provider_charge_id
    order.telegram_payment_charge_id = telegram_payment_charge_id
    order.checkout_chat_id = None
    order.checkout_message_id = None

    await session.commit()
    return order


async def cancel_pending_order(
    session: AsyncSession,
    *,
    order_id: str,
    user_id: int,
) -> Order | None:
    await cleanup_expired_reservations(session, auto_commit=False)

    order = await get_order(session, order_id)
    if order is None:
        return None
    if order.tg_user_id != user_id:
        return None
    if order.status in {OrderStatus.PAID, OrderStatus.DELIVERED}:
        return order
    if order.status in {OrderStatus.CANCELLED, OrderStatus.FAILED}:
        if order.checkout_chat_id is not None or order.checkout_message_id is not None:
            order.checkout_chat_id = None
            order.checkout_message_id = None
            await session.commit()
        return order

    released = await get_sheets_store().release_reserved_items(
        order_id=order.id,
        buyer_tg_id=user_id,
    )
    if released:
        await invalidate_stock_cache()

    order.status = OrderStatus.CANCELLED
    order.checkout_chat_id = None
    order.checkout_message_id = None
    await session.commit()
    return order


async def deliver_order_csv(
    session: AsyncSession,
    *,
    order_id: str,
    export_dir: str,
) -> Path | None:
    order = await get_order(session, order_id)
    if order is None or order.product is None:
        return None

    if order.status not in {OrderStatus.PAID, OrderStatus.DELIVERED}:
        return None

    output_dir = Path(export_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"order_{order.id}.csv"
    if order.status == OrderStatus.DELIVERED and csv_path.exists():
        return csv_path

    claimed_items = await get_sheets_store().claim_reserved_items(
        order_id=order.id,
        buyer_tg_id=order.tg_user_id,
        buyer_username=order.tg_username,
        payment_method=order.payment_method.value,
    )
    if len(claimed_items) < order.quantity:
        return None
    await invalidate_stock_cache()

    include_instruction = any((item.get("extra_instruction") or "").strip() for item in claimed_items)
    preferred_fields = ["item_id", "product", "access_login", "access_secret", "note"]
    if include_instruction:
        preferred_fields.append("extra_instruction")

    excluded = {
        "status",
        "supplier_purchased_at",
        "sold_to_tg_id",
        "sold_to_username",
        "sold_at",
        "order_id",
        "payment_method",
        "reserved_for_order_id",
        "reserved_by_tg_id",
        "reserved_until",
        "reserved_at",
    }

    fieldnames: list[str] = []
    for field in preferred_fields:
        if any(field in item for item in claimed_items):
            fieldnames.append(field)

    for item in claimed_items:
        for key in item.keys():
            if key in excluded:
                continue
            if key == "extra_instruction" and not include_instruction:
                continue
            if key not in fieldnames:
                fieldnames.append(key)

    if not fieldnames:
        fieldnames = list(claimed_items[0].keys())

    with csv_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for item in claimed_items:
            row = {name: str(item.get(name, "")) for name in fieldnames}
            writer.writerow(row)

    await get_sheets_store().append_sale_log(
        order_id=order.id,
        product_slug=order.product.slug,
        quantity=order.quantity,
        buyer_tg_id=order.tg_user_id,
        buyer_username=order.tg_username,
        payment_method=order.payment_method.value,
        total_price=order.total_price,
        currency=order.currency,
        delivered_item_ids=[item.get("item_id", "") for item in claimed_items],
    )

    order.status = OrderStatus.DELIVERED
    await session.commit()
    return csv_path


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


async def set_order_checkout_message(
    session: AsyncSession,
    *,
    order_id: str,
    chat_id: int,
    message_id: int,
    auto_commit: bool = True,
) -> None:
    order = await get_order(session, order_id)
    if order is None:
        return
    order.checkout_chat_id = chat_id
    order.checkout_message_id = message_id
    if auto_commit:
        await session.commit()


async def clear_order_checkout_message(
    session: AsyncSession,
    *,
    order_id: str,
    auto_commit: bool = True,
) -> None:
    order = await get_order(session, order_id)
    if order is None:
        return
    order.checkout_chat_id = None
    order.checkout_message_id = None
    if auto_commit:
        await session.commit()


async def list_cancelled_orders_with_checkout_message(
    session: AsyncSession,
    *,
    limit: int = 100,
) -> Sequence[Order]:
    result = await session.scalars(
        select(Order)
        .where(
            Order.status == OrderStatus.CANCELLED,
            Order.checkout_chat_id.is_not(None),
            Order.checkout_message_id.is_not(None),
        )
        .order_by(Order.updated_at.desc())
        .limit(limit)
    )
    return list(result)


async def find_pending_fiat_order_for_tribute(
    session: AsyncSession,
    *,
    tg_user_id: int,
    amount_cents: int | None = None,
) -> Order | None:
    base_stmt = (
        select(Order)
        .where(
            Order.tg_user_id == tg_user_id,
            Order.payment_method == PaymentMethod.FIAT,
            Order.status.in_([OrderStatus.CREATED, OrderStatus.PENDING_PAYMENT]),
        )
        .options(selectinload(Order.product))
    )

    if amount_cents is not None and amount_cents > 0:
        order_by_amount = await session.scalar(
            base_stmt.where(Order.total_price == amount_cents).order_by(Order.created_at.desc()).limit(1)
        )
        if order_by_amount is not None:
            return order_by_amount

    return await session.scalar(base_stmt.order_by(Order.created_at.desc()).limit(1))


def build_tribute_url(
    *,
    base_url: str,
    order_id: str,
    user_id: int,
    product_slug: str,
    amount_usd_cents: int,
    quantity: int,
) -> str:
    query_data = dict(
        {
            "order_id": order_id,
            "user_id": user_id,
            "product": product_slug,
            "qty": quantity,
            "amount_usd_cents": amount_usd_cents,
        }
    )
    parsed = urlparse(base_url)
    existing_query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    existing_query.update({k: str(v) for k, v in query_data.items()})
    merged = parsed._replace(query=urlencode(existing_query))
    return urlunparse(merged)


def resolve_tribute_base_url(
    *,
    product_slug: str,
    fallback_base_url: str,
    tribute_link_gpt_pro_1m: str,
    tribute_link_gpt_pro_3m: str,
    tribute_link_lovable_100: str,
    tribute_link_lovable_200: str,
    tribute_link_lovable_300: str,
    tribute_link_replit_core: str,
    tribute_link_replit_team: str,
) -> str | None:
    per_product = {
        "gpt-pro-1m": tribute_link_gpt_pro_1m,
        "gpt-pro-3m": tribute_link_gpt_pro_3m,
        "lovable-100": tribute_link_lovable_100,
        "lovable-200": tribute_link_lovable_200,
        "lovable-300": tribute_link_lovable_300,
        "replit-core": tribute_link_replit_core,
        "replit-team": tribute_link_replit_team,
    }
    base = (per_product.get(product_slug) or "").strip() or fallback_base_url.strip()
    lowered = base.lower()
    if not base:
        return None
    if lowered in {"...", "replace_me", "replace_with_value"}:
        return None
    if "tribute.example" in lowered or "replace_" in lowered:
        return None
    return base


def build_tribute_url_for_product(
    *,
    product_slug: str,
    fallback_base_url: str,
    tribute_link_gpt_pro_1m: str,
    tribute_link_gpt_pro_3m: str,
    tribute_link_lovable_100: str,
    tribute_link_lovable_200: str,
    tribute_link_lovable_300: str,
    tribute_link_replit_core: str,
    tribute_link_replit_team: str,
    order_id: str,
    user_id: int,
    amount_usd_cents: int,
    quantity: int,
) -> str | None:
    base = resolve_tribute_base_url(
        product_slug=product_slug,
        fallback_base_url=fallback_base_url,
        tribute_link_gpt_pro_1m=tribute_link_gpt_pro_1m,
        tribute_link_gpt_pro_3m=tribute_link_gpt_pro_3m,
        tribute_link_lovable_100=tribute_link_lovable_100,
        tribute_link_lovable_200=tribute_link_lovable_200,
        tribute_link_lovable_300=tribute_link_lovable_300,
        tribute_link_replit_core=tribute_link_replit_core,
        tribute_link_replit_team=tribute_link_replit_team,
    )
    if base is None:
        return None
    return build_tribute_url(
        base_url=base,
        order_id=order_id,
        user_id=user_id,
        product_slug=product_slug,
        amount_usd_cents=amount_usd_cents,
        quantity=quantity,
    )
