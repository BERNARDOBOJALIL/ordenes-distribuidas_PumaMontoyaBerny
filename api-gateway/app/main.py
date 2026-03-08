import logging
import uuid
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException

from .config import settings
from .schemas import OrderAccepted, OrderCreate, OrderStatus
from .services.order_service import get_order_status, send_to_writer

logger = logging.getLogger("api-gateway")


# ─── Lifecycle ────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http  = httpx.AsyncClient()
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    yield
    await app.state.http.aclose()
    await app.state.redis.aclose()


# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="API Gateway – Ordenes",
    description=(
        "Punto de entrada único del sistema distribuido de órdenes.\n\n"
        "**Flujo escritura**: `POST /orders` → Redis HSET `RECEIVED` → "
        "HTTP POST al writer-service (timeout 1 s + 1 retry).\n\n"
        "**Flujo lectura**: `GET /orders/{order_id}` → HGETALL desde Redis."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ─── Gateway / Health ─────────────────────────────────────────────────────────
@app.get("/", tags=["Gateway"])
async def root():
    return {"gateway": "API Gateway activo", "version": "1.0.0", "docs": "/docs"}


# ─── Ordenes ──────────────────────────────────────────────────────────────────
@app.post(
    "/orders",
    status_code=202,
    response_model=OrderAccepted,
    tags=["Ordenes"],
    summary="Crear orden (202 Accepted)",
)
async def crear_orden(orden: OrderCreate):
    """
    1. Genera order_id (UUID) y X-Request-Id.
    2. HSET order:{id} status=RECEIVED en Redis.
    3. POST /internal/orders al writer-service (timeout 1 s, 1 retry).
    4. Si writer falla → HSET status=FAILED.
    5. Retorna 202 {order_id, status=RECEIVED}.
    """
    order_id = str(uuid.uuid4())
    items_dicts = [item.model_dump() for item in orden.items]

    await send_to_writer(
        app.state.http,
        app.state.redis,
        order_id=order_id,
        customer=orden.customer,
        items=items_dicts,
    )

    return OrderAccepted(order_id=order_id, status="RECEIVED")


@app.get(
    "/orders/{order_id}",
    response_model=OrderStatus,
    tags=["Ordenes"],
    summary="Consultar estado de una orden",
)
async def obtener_orden(order_id: str):
    """Lee HGETALL order:{order_id} desde Redis y devuelve el estado."""
    data = await get_order_status(app.state.redis, order_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Orden {order_id} no encontrada en Redis")
    return data
