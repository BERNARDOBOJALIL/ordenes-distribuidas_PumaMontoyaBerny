"""
Writer Service — internal persistence microservice.

Responsibilities
----------------
- POST /internal/orders : idempotent insert into PostgreSQL.
- Updates Redis hash ``order:{id}`` with status PERSISTED / FAILED.

Flow
----
api-gateway  →  POST /internal/orders  →  PostgreSQL + Redis hash update
"""

import logging
import json
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pika
import redis.asyncio as aioredis
from fastapi import FastAPI, Header, Request

from .config import settings
from .db import AsyncSessionLocal, init_db
from .repositories.orders_repo import upsert_order, get_all_orders
from .schemas import InternalOrder

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("writer-service")


def publish_order_created_event(event: dict) -> None:
    """Blocking publisher using pika; run this inside asyncio.to_thread()."""
    params = pika.URLParameters(settings.amqp_url)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()

    channel.exchange_declare(
        exchange=settings.rabbitmq_exchange,
        exchange_type="topic",
        durable=True,
    )

    channel.basic_publish(
        exchange=settings.rabbitmq_exchange,
        routing_key=settings.order_created_routing_key,
        body=json.dumps(event),
        properties=pika.BasicProperties(
            content_type="application/json",
            delivery_mode=2,
        ),
    )
    connection.close()


# ─── Lifecycle ────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    await init_db()
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    logger.info("[App] DB tables ready. Redis connected.")
    yield
    # shutdown
    await app.state.redis.aclose()
    logger.info("[App] Shutdown complete.")


# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Order Service – Órdenes",
    description=(
        "Servicio interno que persiste órdenes en PostgreSQL y publica eventos.\n\n"
        "Recibe peticiones del api-gateway vía `POST /internal/orders` "
        "e implementa un `upsert_order` idempotente + evento `order.created` en RabbitMQ."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ─── Health ───────────────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
async def root():
    return {"service": "order-service", "status": "ok", "version": "1.0.0"}


# ─── Internal endpoint ────────────────────────────────────────────────────────
@app.post(
    "/internal/orders",
    status_code=201,
    tags=["Internal"],
    summary="Persiste una orden en PostgreSQL (idempotente)",
)
async def persist_order(
    payload: InternalOrder,
    request: Request,
    x_request_id: str = Header(default=""),
):
    """
    Receives an order from the api-gateway, inserts it into PostgreSQL
    (only if order_id does not already exist), and updates the Redis hash
    with status = PERSISTED or FAILED.
    """
    redis = request.app.state.redis
    request_id = x_request_id
    logger.info(
        "[POST /internal/orders] order_id=%s  X-Request-Id=%s",
        payload.order_id,
        request_id,
    )

    try:
        async with AsyncSessionLocal() as session:
            order, created = await upsert_order(
                session,
                order_id=payload.order_id,
                customer=payload.customer,
                items=[item.model_dump() for item in payload.items],
            )

        if created:
            event = {
                "event_type": "order.created",
                "order_id": payload.order_id,
                "customer": payload.customer,
                "items": [item.model_dump() for item in payload.items],
                "created_at": order.created_at.isoformat() if order.created_at else datetime.now(timezone.utc).isoformat(),
                "request_id": request_id,
            }
            await asyncio.to_thread(publish_order_created_event, event)
            logger.info("[POST /internal/orders] event published routing_key=%s order_id=%s", settings.order_created_routing_key, payload.order_id)

        now = datetime.now(timezone.utc).isoformat()
        await redis.hset(
            f"order:{payload.order_id}",
            mapping={"status": "PERSISTED", "last_update": now},
        )
        logger.info(
            "[POST /internal/orders] ✓ %s order_id=%s",
            "Created" if created else "Already existed",
            payload.order_id,
        )
        return {"order_id": payload.order_id, "status": "PERSISTED", "created": created}

    except Exception as exc:
        now = datetime.now(timezone.utc).isoformat()
        await redis.hset(
            f"order:{payload.order_id}",
            mapping={"status": "FAILED", "last_update": now},
        )
        logger.error(
            "[POST /internal/orders] ✗ FAILED order_id=%s: %s",
            payload.order_id,
            exc,
        )
        return {"order_id": payload.order_id, "status": "FAILED", "error": str(exc)}


# ─── List orders ──────────────────────────────────────────────────────────────
@app.get(
    "/internal/orders",
    tags=["Internal"],
    summary="Lista todas las órdenes desde PostgreSQL",
)
async def list_orders(request: Request):
    """Devuelve todas las órdenes guardadas en PostgreSQL."""
    import json as _json
    async with AsyncSessionLocal() as session:
        orders = await get_all_orders(session)
    return [
        {
            "order_id": o.order_id,
            "customer": o.customer,
            "items": _json.loads(o.items),
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in orders
    ]