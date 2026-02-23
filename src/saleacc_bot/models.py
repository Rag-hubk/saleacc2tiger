from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class InventoryStatus(str, enum.Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    SOLD = "sold"


class OrderStatus(str, enum.Enum):
    CREATED = "created"
    PENDING_PAYMENT = "pending_payment"
    PAID = "paid"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    FAILED = "failed"


class PaymentMethod(str, enum.Enum):
    CRYPTO = "crypto"
    FIAT = "fiat"
    STARS = "stars"  # legacy
    TRIBUTE = "tribute"  # legacy


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(512), default="")

    price_usd_cents: Mapped[int] = mapped_column(Integer, default=5000)
    price_stars: Mapped[int] = mapped_column(Integer, default=5000)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    inventory_items: Mapped[list[InventoryItem]] = relationship(back_populates="product")
    orders: Mapped[list[Order]] = relationship(back_populates="product")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    tg_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)

    payment_method: Mapped[PaymentMethod] = mapped_column(Enum(PaymentMethod), index=True)
    currency: Mapped[str] = mapped_column(String(8))
    unit_price: Mapped[int] = mapped_column(Integer)
    total_price: Mapped[int] = mapped_column(Integer)

    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), index=True, default=OrderStatus.CREATED)

    provider_charge_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    telegram_payment_charge_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    product: Mapped[Product] = relationship(back_populates="orders")
    order_items: Mapped[list[OrderItem]] = relationship(back_populates="order")


class BotUser(Base):
    __tablename__ = "bot_users"

    tg_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tg_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)

    secret_ciphertext: Mapped[str] = mapped_column(Text)
    status: Mapped[InventoryStatus] = mapped_column(Enum(InventoryStatus), index=True)

    reserved_for_order_id: Mapped[Optional[str]] = mapped_column(ForeignKey("orders.id"), nullable=True, index=True)
    reserved_by_tg_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    reserved_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    sold_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    product: Mapped[Product] = relationship(back_populates="inventory_items")
    order_item: Mapped[Optional[OrderItem]] = relationship(back_populates="inventory_item", uselist=False)


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (UniqueConstraint("inventory_item_id", name="uq_order_items_inventory"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    inventory_item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), index=True)

    delivered_csv_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    order: Mapped[Order] = relationship(back_populates="order_items")
    inventory_item: Mapped[InventoryItem] = relationship(back_populates="order_item")
