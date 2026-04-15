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


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, examples=["admin"])
    password: str = Field(..., min_length=8, examples=["ChangeMe123!"])


class SignupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=255, examples=["newuser"])
    email: str = Field(..., min_length=5, max_length=255, examples=["newuser@example.com"])
    password: str = Field(..., min_length=8, examples=["ChangeMe123!"])


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=20)


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class MeResponse(BaseModel):
    user_id: str
    username: str
    email: str
