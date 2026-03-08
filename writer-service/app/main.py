"""
Writer Service — internal persistence microservice.

Responsibilities
----------------
1. Background Redis worker: polls ``orders_queue`` every WORKER_INTERVAL
   seconds, deserialises each message and persists it in PostgreSQL.
2. REST endpoints proxied by the api-gateway:
   GET  /orders          — list all orders
   GET  /orders/{id}     — single order
   PUT  /orders/{id}     — partial update
   DELETE /orders/{id}   — remove

Flow
----
api-gateway  →  lpush(orders_queue, JSON)
                              ↓  (async, every 10 s)
              redis_queue_worker  →  PostgreSQL (via AsyncSession)
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import List

import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import AsyncSessionLocal, get_session, init_db
from .redis_client import get_redis_client
from .repositories.orders_repo import (
    delete_order,
    get_order,
    list_orders,
    update_order,
    upsert_order,
)
from .schemas import OrderResponse, OrderUpdate

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("writer-service")


# ─── Background Redis worker ──────────────────────────────────────────────────
async def redis_queue_worker(redis: aioredis.Redis) -> None:
    """
    Infinite loop that consumes one message per tick from ``orders_queue``.

    Uses rpop (pairs with api-gateway's lpush) for FIFO ordering.
    On DB failure the raw message is pushed back to avoid data loss.
    """
    logger.info(
        "[WORKER] Started — polling '%s' every %ds",
        settings.queue_name,
        settings.worker_interval,
    )
    while True:
        await asyncio.sleep(settings.worker_interval)
        try:
            raw = await redis.rpop(settings.queue_name)
            if raw is None:
                logger.debug("[WORKER] Queue empty — waiting %ds …", settings.worker_interval)
                continue

            data: dict = json.loads(raw)
            logger.info("[WORKER] Processing order: %s", data)

            async with AsyncSessionLocal() as session:
                try:
                    order = await upsert_order(session, data)
                    logger.info(
                        "[WORKER] ✓ Saved — id=%d, cliente=%s",
                        order.id,
                        order.cliente,
                    )
                except Exception as db_err:
                    logger.error("[WORKER] DB error — returning message to queue: %s", db_err)
                    await redis.rpush(settings.queue_name, raw)

        except asyncio.CancelledError:
            logger.info("[WORKER] Cancelled — shutting down.")
            break
        except Exception as err:
            logger.error("[WORKER] Unexpected error: %s", err)


# ─── Lifecycle ────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    await init_db()
    redis = get_redis_client()
    worker_task = asyncio.create_task(redis_queue_worker(redis))
    logger.info("[App] DB tables ready. Redis worker running.")
    yield
    # shutdown
    worker_task.cancel()
    await redis.aclose()
    logger.info("[App] Shutdown complete.")


# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Writer Service – Órdenes",
    description=(
        "Servicio interno que persiste órdenes en PostgreSQL.\n\n"
        "Consume la cola Redis **orders_queue** cada "
        f"**{settings.worker_interval} s** e implementa un `upsert_order` idempotente."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ─── Health ───────────────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
async def root():
    return {"service": "writer-service", "status": "ok", "version": "1.0.0"}


# ─── Orders ───────────────────────────────────────────────────────────────────
@app.get(
    "/orders",
    response_model=List[OrderResponse],
    tags=["Órdenes"],
    summary="Listar órdenes",
)
async def listar_ordenes(
    skip: int = 0,
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
):
    """Devuelve todas las órdenes almacenadas (paginadas con skip/limit)."""
    return await list_orders(session, skip=skip, limit=limit)


@app.get(
    "/orders/{orden_id}",
    response_model=OrderResponse,
    tags=["Órdenes"],
    summary="Obtener orden por ID",
)
async def obtener_orden(
    orden_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Devuelve una orden por su ID entero."""
    order = await get_order(session, orden_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"Orden {orden_id} no encontrada")
    return order


@app.put(
    "/orders/{orden_id}",
    response_model=OrderResponse,
    tags=["Órdenes"],
    summary="Actualizar orden (parcial)",
)
async def actualizar_orden(
    orden_id: int,
    datos: OrderUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Actualiza sólo los campos enviados en el body (PATCH semántico)."""
    changes = datos.model_dump(exclude_unset=True)
    order = await update_order(session, orden_id, changes)
    if not order:
        raise HTTPException(status_code=404, detail=f"Orden {orden_id} no encontrada")
    return order


@app.delete(
    "/orders/{orden_id}",
    status_code=204,
    tags=["Órdenes"],
    summary="Eliminar orden",
)
async def eliminar_orden(
    orden_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Elimina una orden por su ID. Devuelve 204 sin cuerpo."""
    deleted = await delete_order(session, orden_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Orden {orden_id} no encontrada")
