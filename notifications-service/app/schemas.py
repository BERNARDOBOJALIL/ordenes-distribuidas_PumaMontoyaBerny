from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ItemPayload(BaseModel):
    sku: str = Field(..., examples=["A1"])
    qty: int = Field(..., gt=0, examples=[2])


class NotificationCreate(BaseModel):
    """Payload recibido para crear una notificación."""

    order_id: str = Field(..., examples=["550e8400-e29b-41d4-a716-446655440000"])
    customer: str = Field(..., examples=["Berny"])
    event_type: str = Field(..., examples=["order.created"])
    message: str = Field(..., examples=["Orden creada exitosamente"])
    reason: Optional[str] = Field(None, examples=["Pedido confirmado exitosamente"])
    items: List[ItemPayload] = Field(default_factory=list, examples=[[{"sku": "A1", "qty": 2}]])


class NotificationResponse(BaseModel):
    """Respuesta al consultar una notificación."""

    id: int
    order_id: str
    customer: str
    event_type: str
    message: str
    reason: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
