from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class ProductCreate(BaseModel):
    sku: str = Field(..., examples=["LAPTOP-01"])
    name: str = Field(..., examples=["Laptop Gamer 15"])
    description: Optional[str] = Field(None, examples=["Laptop con RTX 4060"])
    price: Decimal = Field(..., ge=0, examples=[24999.99])
    stock: int = Field(..., ge=0, examples=[50])


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[Decimal] = Field(None, ge=0)
    stock: Optional[int] = Field(None, ge=0)


class ProductResponse(BaseModel):
    sku: str
    name: str
    description: Optional[str]
    price: Decimal
    stock: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    model_config = {"from_attributes": True}


class StockCheckItem(BaseModel):
    sku: str = Field(..., examples=["LAPTOP-01"])
    qty: int = Field(..., gt=0, examples=[2])


class StockCheckRequest(BaseModel):
    items: List[StockCheckItem]


class StockCheckResult(BaseModel):
    sku: str
    requested: int
    available: int
    sufficient: bool


class StockCheckResponse(BaseModel):
    all_available: bool
    details: List[StockCheckResult]
