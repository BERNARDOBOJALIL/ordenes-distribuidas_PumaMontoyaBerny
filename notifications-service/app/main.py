"""
Notifications Service — internal persistence + email notification microservice.

Responsibilities
----------------
- POST /internal/notifications : persists notification in PostgreSQL + sends email via EmailJS.
- GET  /internal/notifications : lists all notifications.
- GET  /internal/notifications/{order_id} : notifications for a specific order.
"""

import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request

from .config import settings
from .db import AsyncSessionLocal, init_db
from .repositories.notifications_repo import (
    create_notification,
    get_all_notifications,
    get_notifications_by_order,
)
from .schemas import NotificationCreate, NotificationResponse
from .services.email_service import send_email_notification

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("notifications-service")


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
    title="Notifications Service",
    description=(
        "Servicio interno que persiste notificaciones en PostgreSQL "
        "y envía emails de confirmación vía EmailJS."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ─── Health ───────────────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
async def root():
    return {"service": "notifications-service", "status": "ok", "version": "1.0.0"}


# ─── Internal endpoints ──────────────────────────────────────────────────────
@app.post(
    "/internal/notifications",
    status_code=201,
    response_model=NotificationResponse,
    tags=["Internal"],
    summary="Crea una notificación y envía email",
)
async def persist_notification(payload: NotificationCreate, request: Request):
    """
    1. Guarda la notificación en PostgreSQL.
    2. Envía email de confirmación vía EmailJS (fire-and-forget).
    3. Retorna la notificación creada.
    """
    logger.info(
        "[POST /internal/notifications] order_id=%s  event=%s",
        payload.order_id,
        payload.event_type,
    )

    async with AsyncSessionLocal() as session:
        notification = await create_notification(
            session,
            order_id=payload.order_id,
            customer=payload.customer,
            event_type=payload.event_type,
            message=payload.message,
            reason=payload.reason,
        )

    # Enviar email (no bloquea la respuesta si falla)
    try:
        await send_email_notification(
            order_id=payload.order_id,
            customer=payload.customer,
            event_type=payload.event_type,
            message=payload.message,
            items=[item.model_dump() for item in payload.items],
        )
        logger.info("[POST /internal/notifications] ✓ Email sent for order_id=%s", payload.order_id)
    except Exception as exc:
        logger.warning(
            "[POST /internal/notifications] ⚠ Email failed for order_id=%s: %s",
            payload.order_id,
            exc,
        )

    return notification


@app.get(
    "/internal/notifications",
    response_model=list[NotificationResponse],
    tags=["Internal"],
    summary="Lista todas las notificaciones",
)
async def list_notifications():
    """Devuelve todas las notificaciones desde PostgreSQL."""
    async with AsyncSessionLocal() as session:
        notifications = await get_all_notifications(session)
    return notifications


@app.get(
    "/internal/notifications/{order_id}",
    response_model=list[NotificationResponse],
    tags=["Internal"],
    summary="Notificaciones de una orden específica",
)
async def get_order_notifications(order_id: str):
    """Devuelve todas las notificaciones asociadas a un order_id."""
    async with AsyncSessionLocal() as session:
        notifications = await get_notifications_by_order(session, order_id)
    return notifications
