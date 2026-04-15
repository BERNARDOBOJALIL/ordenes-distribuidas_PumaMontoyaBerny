import logging
import uuid
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
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


@app.get(
    "/orders",
    tags=["Ordenes"],
    summary="Listar todas las órdenes (desde PostgreSQL vía writer-service)",
)
async def listar_ordenes():
    """Proxy a GET /internal/orders del writer-service."""
    try:
        url = f"{settings.writer_service_url}/internal/orders"
        resp = await app.state.http.get(url, timeout=5.0)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Writer service no disponible: {exc}")


@app.get(
    "/inventory/stock",
    tags=["Inventory"],
    summary="Consultar stock actual desde inventory-service",
)
async def get_inventory_stock():
    """Proxy a GET /internal/stock del inventory-service."""
    try:
        url = f"{settings.inventory_service_url}/internal/stock"
        resp = await app.state.http.get(url, timeout=5.0)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Inventory service no disponible: {exc}")


# ─── Productos ────────────────────────────────────────────────────────────────
@app.get(
    "/products",
    tags=["Productos"],
    summary="Listar todos los productos",
)
async def listar_productos():
    """Proxy a GET /internal/products del writer-service."""
    try:
        url = f"{settings.writer_service_url}/internal/products"
        resp = await app.state.http.get(url, timeout=5.0)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Writer service no disponible: {exc}")


@app.get(
    "/products/{sku}",
    tags=["Productos"],
    summary="Obtener producto por SKU",
)
async def obtener_producto(sku: str):
    """Proxy a GET /internal/products/{sku} del writer-service."""
    try:
        url = f"{settings.writer_service_url}/internal/products/{sku}"
        resp = await app.state.http.get(url, timeout=5.0)
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Producto {sku} no encontrado")
        resp.raise_for_status()
        return resp.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Writer service no disponible: {exc}")