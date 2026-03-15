from pydantic import BaseModel, ConfigDict, Field


class OrderItem(BaseModel):
    sku: str = Field(min_length=1)
    qty: int = Field(gt=0)


class OrderCreatedEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_type: str = "order.created"
    order_id: str = Field(min_length=1)
    customer: str = Field(min_length=1)
    items: list[OrderItem] = Field(default_factory=list)
    created_at: str | None = None
    request_id: str | None = None
