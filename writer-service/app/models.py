from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Order(Base):
    """ORM model — matches the README spec."""

    __tablename__ = "orders"

    order_id   = Column(String(36), primary_key=True, index=True)
    customer   = Column(String(255), nullable=False)
    items      = Column(Text, nullable=False)          
    created_at = Column(DateTime, default=lambda: datetime.utcnow())


class Product(Base):
    """Catálogo de productos."""

    __tablename__ = "products"

    sku         = Column(String(50), primary_key=True, index=True)
    name        = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    price       = Column(Float, nullable=False)
    stock       = Column(Integer, nullable=False, default=0)
    created_at  = Column(DateTime, default=lambda: datetime.utcnow())
