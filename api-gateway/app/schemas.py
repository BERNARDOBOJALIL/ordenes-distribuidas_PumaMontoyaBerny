from pydantic import BaseModel, Field
from typing import Optional


class OrderCreate(BaseModel):
    cliente:  str   = Field(..., examples=["Juan Pérez"])
    producto: str   = Field(..., examples=["Laptop"])
    cantidad: int   = Field(..., gt=0, examples=[2])
    precio:   float = Field(..., gt=0, examples=[999.99])
    estado:   Optional[str] = Field("pendiente", examples=["pendiente"])

    model_config = {
        "json_schema_extra": {
            "example": {
                "cliente": "Juan Pérez",
                "producto": "Laptop",
                "cantidad": 2,
                "precio": 999.99,
                "estado": "pendiente",
            }
        }
    }


class OrderUpdate(BaseModel):
    cliente:  Optional[str]   = None
    producto: Optional[str]   = None
    cantidad: Optional[int]   = Field(None, gt=0)
    precio:   Optional[float] = Field(None, gt=0)
    estado:   Optional[str]   = None


class OrderQueued(BaseModel):
    message:          str
    status:           str
    posicion_en_cola: int
    tiempo_estimado:  str
