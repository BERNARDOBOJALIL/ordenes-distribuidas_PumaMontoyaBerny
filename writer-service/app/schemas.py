from typing import Any, List

from pydantic import BaseModel, Field


class ItemPayload(BaseModel):
    sku: str = Field(..., examples=["A1"])
    qty: int = Field(..., gt=0, examples=[2])


class InternalOrder(BaseModel):
    """Payload received from api-gateway via POST /internal/orders."""

    order_id: str = Field(..., examples=["550e8400-e29b-41d4-a716-446655440000"])
    customer: str = Field(..., examples=["Berny"])
    items:    List[ItemPayload] = Field(..., examples=[[{"sku": "A1", "qty": 2}]])
