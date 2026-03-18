"""
Service layer — HTTP call to writer-service with timeout + retry + X-Request-Id.
"""

import logging
import uuid
from datetime import datetime, timezone

import httpx

from ..config import settings

logger = logging.getLogger("api-gateway")


async def send_to_writer(
    http_client: httpx.AsyncClient,
    redis,
    order_id: str,
    customer: str,
    items: list[dict],
) -> str:
    """
    1. HSET order:{id} status=RECEIVED in Redis.
    2. POST /internal/orders to writer-service (timeout + retry).
    3. On failure: HSET status=FAILED.
    Returns the final status string.
    """
    request_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # ① Mark RECEIVED in Redis
    await redis.hset(
        f"order:{order_id}",
        mapping={"status": "RECEIVED", "last_update": now},
    )

    payload = {"order_id": order_id, "customer": customer, "items": items}
    headers = {"X-Request-Id": request_id}
    url = f"{settings.writer_service_url}/internal/orders"
    timeout = httpx.Timeout(settings.writer_timeout_seconds)

    attempts = 1 + settings.writer_max_retries  # 1 try + N retries
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            logger.info(
                "[send_to_writer] attempt %d/%d  order_id=%s  X-Request-Id=%s",
                attempt, attempts, order_id, request_id,
            )
            resp = await http_client.post(url, json=payload, headers=headers, timeout=timeout)
            if resp.status_code == 201:
                logger.info("[send_to_writer] ✓ Writer returned 201 for order_id=%s", order_id)
                return "RECEIVED"
            if 400 <= resp.status_code < 500:
                # Error de negocio (ej. stock insuficiente) — propagar al cliente sin reintentar
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.json().get("detail", resp.text),
                )
            last_error = Exception(f"Writer returned {resp.status_code}")
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_error = exc
            logger.warning("[send_to_writer] attempt %d failed: %s", attempt, exc)

    # All attempts exhausted — mark FAILED
    now = datetime.now(timezone.utc).isoformat()
    await redis.hset(
        f"order:{order_id}",
        mapping={"status": "FAILED", "last_update": now},
    )
    logger.error("[send_to_writer] ✗ FAILED order_id=%s after %d attempts: %s", order_id, attempts, last_error)
    return "FAILED"


async def get_order_status(redis, order_id: str) -> dict | None:
    """Read order:{id} hash from Redis."""
    data = await redis.hgetall(f"order:{order_id}")
    if not data:
        return None
    return {"order_id": order_id, **data}
