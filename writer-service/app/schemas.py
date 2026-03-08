from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class OrderCreate(BaseModel):
    """Payload that the api-gateway enqueues / sends directly."""

    cliente:  str   = Field(..., examples=["Juan Pérez"])
    producto: str   = Field(..., examples=["Laptop"])
    cantidad: int   = Field(..., gt=0, examples=[2])
    precio:   float = Field(..., gt=0, examples=[999.99])
    estado:   Optional[str] = Field("pendiente", examples=["pendiente"])


class OrderUpdate(BaseModel):
    """Partial update payload (all fields optional)."""

    cliente:  Optional[str]   = None
    producto: Optional[str]   = None
    cantidad: Optional[int]   = Field(None, gt=0)
    precio:   Optional[float] = Field(None, gt=0)
    estado:   Optional[str]   = None


class OrderResponse(BaseModel):
    """Response schema returned to the api-gateway and, transitively, to the client."""

    id:        int
    cliente:   str
    producto:  str
    cantidad:  int
    precio:    float
    estado:    str
    creado_en: datetime

    model_config = {"from_attributes": True}
