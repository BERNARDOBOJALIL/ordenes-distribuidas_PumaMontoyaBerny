from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Order(Base):
    """ORM model that mirrors the api-gateway payload schema."""

    __tablename__ = "orders"

    id        = Column(Integer, primary_key=True, index=True, autoincrement=True)
    cliente   = Column(String(255), nullable=False)
    producto  = Column(String(255), nullable=False)
    cantidad  = Column(Integer, nullable=False)
    precio    = Column(Float, nullable=False)
    estado    = Column(String(50), default="pendiente")
    creado_en = Column(DateTime, default=datetime.utcnow)
