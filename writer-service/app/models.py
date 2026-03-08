from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Order(Base):
    """ORM model — matches the README spec."""

    __tablename__ = "orders"

    order_id   = Column(String(36), primary_key=True, index=True)
    customer   = Column(String(255), nullable=False)
    items      = Column(Text, nullable=False)          # JSON string
    created_at = Column(DateTime, default=lambda: datetime.utcnow())
