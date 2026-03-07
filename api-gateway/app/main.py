from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .config import settings
from .schemas import OrderCreate, OrderQueued, OrderUpdate
from .services.order_service import enqueue_order, forward_request


# ─── Lifecycle ────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http  = httpx.AsyncClient(timeout=httpx.Timeout(settings.http_timeout))
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    yield
    await app.state.http.aclose()
    await app.state.redis.aclose()


# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="API Gateway – Ordenes",
    description=(
        "Punto de entrada unico del sistema distribuido de ordenes.\n\n"
        "**Flujo escritura**: `POST /orders` encola en Redis; "
        "el writer-service consume y persiste en PostgreSQL (~10 s).\n\n"
        "**Flujo lectura/edicion/borrado**: el gateway reenvía la peticion "
        "directamente al writer-service."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ─── Gateway / Health ─────────────────────────────────────────────────────────
@app.get("/", tags=["Gateway"])
async def root():
    return {
        "gateway": "API Gateway activo",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health", tags=["Gateway"])
async def health():
    """Health-check del gateway y sus dependencias."""
    services: dict[str, str] = {}

    try:
        r = await app.state.http.get(f"{settings.writer_service_url}/", timeout=3.0)
        services["writer-service"] = "ok" if r.status_code == 200 else f"error {r.status_code}"
    except Exception as exc:
        services["writer-service"] = f"down ({exc})"

    try:
        await app.state.redis.ping()
        queue_len = await app.state.redis.llen(settings.queue_name)
        services["redis"] = f"ok (cola: {queue_len} pendientes)"
    except Exception as exc:
        services["redis"] = f"down ({exc})"

    all_ok = all(v.startswith("ok") for v in services.values())
    return JSONResponse(
        status_code=200 if all_ok else 207,
        content={"status": "ok" if all_ok else "degraded", "services": services},
    )


@app.get("/queue/status", tags=["Gateway"])
async def queue_status():
    """Cuantas ordenes hay pendientes en la cola Redis."""
    try:
        length = await app.state.redis.llen(settings.queue_name)
        return {"queue": settings.queue_name, "pendientes": length}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Redis no disponible: {exc}")


# ─── Ordenes ──────────────────────────────────────────────────────────────────
@app.post(
    "/orders",
    status_code=202,
    response_model=OrderQueued,
    tags=["Ordenes"],
    summary="Crear orden (asincrono via Redis)",
)
async def crear_orden(orden: OrderCreate):
    """
    Recibe la orden, la serializa y la encola en Redis.
    El writer-service la consume y persiste en PostgreSQL ~10 segundos despues.
    """
    return await enqueue_order(app.state.redis, orden.model_dump())


@app.get("/orders", tags=["Ordenes"], summary="Listar ordenes")
async def listar_ordenes(request: Request):
    """Devuelve todas las ordenes almacenadas en PostgreSQL (via writer-service)."""
    return await forward_request(app.state.http, request, "/orders")


@app.get("/orders/{orden_id}", tags=["Ordenes"], summary="Obtener orden por ID")
async def obtener_orden(request: Request, orden_id: int):
    """Devuelve una orden especifica por su ID."""
    return await forward_request(app.state.http, request, f"/orders/{orden_id}")


@app.put("/orders/{orden_id}", tags=["Ordenes"], summary="Actualizar orden")
async def actualizar_orden(request: Request, orden_id: int):
    """Actualiza los campos de una orden existente (via writer-service)."""
    return await forward_request(app.state.http, request, f"/orders/{orden_id}")


@app.delete(
    "/orders/{orden_id}",
    status_code=204,
    tags=["Ordenes"],
    summary="Eliminar orden",
)
async def eliminar_orden(request: Request, orden_id: int):
    """Elimina una orden por ID (via writer-service)."""
    return await forward_request(app.state.http, request, f"/orders/{orden_id}")
