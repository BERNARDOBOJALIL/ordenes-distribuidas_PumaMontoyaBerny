from typing import List, Optional

from pydantic import BaseModel, Field


class ItemPayload(BaseModel):
    sku: str = Field(..., examples=["A1"])
    qty: int = Field(..., gt=0, examples=[2])


class OrderCreate(BaseModel):
    """Body of POST /orders."""
    customer: str = Field(..., examples=["Berny"])
    items: List[ItemPayload] = Field(..., examples=[[{"sku": "A1", "qty": 2}]])


class OrderAccepted(BaseModel):
    """202 response when an order is accepted."""
    order_id: str
    status: str = "RECEIVED"


class OrderStatus(BaseModel):
    """GET /orders/{order_id} response from Redis hash."""
    order_id: str
    status: str
    last_update: Optional[str] = None
