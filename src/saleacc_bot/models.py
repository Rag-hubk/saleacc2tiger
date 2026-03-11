from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    price_kopecks: Mapped[int] = mapped_column(Integer, default=50000)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    orders: Mapped[list[Order]] = relationship(back_populates="product")


class BotUser(Base):
    __tablename__ = "bot_users"

    tg_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tg_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    tg_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_email: Mapped[str] = mapped_column(String(255), index=True)

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    product_slug: Mapped[str] = mapped_column(String(64), index=True)
    product_title: Mapped[str] = mapped_column(String(128))

    quantity: Mapped[int] = mapped_column(Integer, default=1)
    payment_method: Mapped[str] = mapped_column(String(32), default="yookassa", index=True)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    unit_price: Mapped[int] = mapped_column(Integer)
    total_price: Mapped[int] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(String(32), default="pending_payment", index=True)
    provider_payment_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    provider_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    payment_confirmation_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    product: Mapped[Product] = relationship(back_populates="orders")
