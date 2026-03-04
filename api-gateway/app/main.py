"""
API Gateway
───────────
Punto de entrada único del sistema distribuido.

Flujo de creación de órdenes:
  Cliente → POST /orders → gateway → LPUSH Redis (cola)
                                       └── orders-api worker → 10s → PostgreSQL

Flujo de lectura/edición/borrado:
  Cliente → GET|PUT|DELETE /orders/{id} → gateway → orders-api → PostgreSQL
"""

from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import JSONResponse
import httpx
import redis.asyncio as aioredis
import json
import os

# ─── Config ───────────────────────────────────────────────────────────────────
ORDERS_API_URL = os.getenv("ORDERS_API_URL", "http://orders-api:8001")
REDIS_URL      = os.getenv("REDIS_URL",      "redis://redis:6379")
QUEUE_NAME     = "orders_queue"
TIMEOUT        = httpx.Timeout(15.0)

app = FastAPI(
    title="API Gateway",
    description="Gateway del sistema distribuido de órdenes",
    version="2.0.0",
)


# ─── Lifecycle ────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    app.state.client = httpx.AsyncClient(timeout=TIMEOUT)
    app.state.redis  = aioredis.from_url(REDIS_URL, decode_responses=True)
    print("[Gateway] Conectado a Redis y HTTP client listo")


@app.on_event("shutdown")
async def shutdown():
    await app.state.client.aclose()
    await app.state.redis.aclose()


# ─── Helper proxy ─────────────────────────────────────────────────────────────
async def forward(request: Request, base_url: str, path: str) -> Response:
    url  = f"{base_url}{path}"
    body = await request.body()
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length", "transfer-encoding")
    }
    try:
        resp = await app.state.client.request(
            method=request.method,
            url=url,
            headers=headers,
            content=body,
            params=dict(request.query_params),
        )
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail=f"Servicio no disponible: {base_url}")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timeout al conectar con el servicio")

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=dict(resp.headers),
        media_type=resp.headers.get("content-type"),
    )


# ─── Root / Health ────────────────────────────────────────────────────────────
@app.get("/", tags=["Gateway"])
async def root():
    return {
        "gateway": "API Gateway activo ✓",
        "version": "2.0.0",
        "flujo": "POST /orders → Redis queue → worker(10s) → PostgreSQL",
    }


@app.get("/health", tags=["Gateway"])
async def health():
    """Health-check del gateway y dependencias."""
    services = {}

    # orders-api
    try:
        r = await app.state.client.get(f"{ORDERS_API_URL}/", timeout=3.0)
        services["orders-api"] = "ok" if r.status_code == 200 else f"error {r.status_code}"
    except Exception as exc:
        services["orders-api"] = f"down ({exc})"

    # Redis
    try:
        await app.state.redis.ping()
        queue_len = await app.state.redis.llen(QUEUE_NAME)
        services["redis"] = f"ok (cola: {queue_len} órdenes pendientes)"
    except Exception as exc:
        services["redis"] = f"down ({exc})"

    all_ok = all(v.startswith("ok") for v in services.values())
    return JSONResponse(
        status_code=200 if all_ok else 207,
        content={"status": "ok" if all_ok else "degraded", "services": services},
    )


@app.get("/queue/status", tags=["Gateway"])
async def queue_status():
    """Cuántas órdenes hay pendientes en la cola Redis."""
    try:
        length = await app.state.redis.llen(QUEUE_NAME)
        return {"queue": QUEUE_NAME, "pendientes": length}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Redis no disponible: {exc}")


# ─── Órdenes ──────────────────────────────────────────────────────────────────

@app.post("/orders/", status_code=202, tags=["Órdenes"])
@app.post("/orders", status_code=202, tags=["Órdenes"])
async def encolar_orden(request: Request):
    """
    Recibe una orden del cliente y la encola en Redis.
    El worker de orders-api la procesará ~10 segundos después
    y la guardará en PostgreSQL.
    """
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Body vacío")

    # Validar que sea JSON válido
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Body debe ser JSON válido")

    await app.state.redis.lpush(QUEUE_NAME, json.dumps(payload))
    queue_len = await app.state.redis.llen(QUEUE_NAME)

    return {
        "message": "Orden recibida y en cola ✓",
        "status": "en_cola",
        "posicion_en_cola": queue_len,
        "tiempo_estimado": "~10 segundos",
    }


@app.get("/orders/", tags=["Órdenes"])
@app.get("/orders", tags=["Órdenes"])
async def listar_ordenes(request: Request):
    """Lista las órdenes ya procesadas en PostgreSQL."""
    return await forward(request, ORDERS_API_URL, "/orders/")


@app.get("/orders/{orden_id}", tags=["Órdenes"])
async def obtener_orden(request: Request, orden_id: int):
    """Obtiene una orden por ID desde PostgreSQL."""
    return await forward(request, ORDERS_API_URL, f"/orders/{orden_id}")


@app.put("/orders/{orden_id}", tags=["Órdenes"])
async def actualizar_orden(request: Request, orden_id: int):
    """Actualiza una orden existente en PostgreSQL."""
    return await forward(request, ORDERS_API_URL, f"/orders/{orden_id}")


@app.delete("/orders/{orden_id}", tags=["Órdenes"])
async def eliminar_orden(request: Request, orden_id: int):
    """Elimina una orden por ID de PostgreSQL."""
    return await forward(request, ORDERS_API_URL, f"/orders/{orden_id}")


app = FastAPI(
    title="API Gateway",
    description="Gateway principal del sistema distribuido de órdenes",
    version="1.0.0",
)


# ─── Cliente HTTP compartido ───────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    app.state.client = httpx.AsyncClient(timeout=TIMEOUT)


@app.on_event("shutdown")
async def shutdown():
    await app.state.client.aclose()


# ─── Helper para reenviar peticiones ──────────────────────────────────────────
async def forward(request: Request, base_url: str, path: str) -> Response:
    url = f"{base_url}{path}"
    body = await request.body()

    # Cabeceras útiles para reenviar (sin las de hop-by-hop)
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length", "transfer-encoding")
    }

    try:
        resp = await app.state.client.request(
            method=request.method,
            url=url,
            headers=headers,
            content=body,
            params=dict(request.query_params),
        )
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail=f"Servicio no disponible: {base_url}")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timeout al conectar con el servicio")

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=dict(resp.headers),
        media_type=resp.headers.get("content-type"),
    )


# ─── Root ─────────────────────────────────────────────────────────────────────
@app.get("/", tags=["Gateway"])
async def root():
    return {
        "gateway": "API Gateway activo ✓",
        "version": "1.0.0",
        "servicios": {
            "orders": f"{ORDERS_API_URL}/orders/",
            # "redis": "pendiente",
        },
    }


@app.get("/health", tags=["Gateway"])
async def health():
    """Health-check del gateway y sus dependencias."""
    services = {}

    # Verificar orders-api
    try:
        r = await app.state.client.get(f"{ORDERS_API_URL}/", timeout=3.0)
        services["orders-api"] = "ok" if r.status_code == 200 else f"error {r.status_code}"
    except Exception as exc:
        services["orders-api"] = f"down ({exc})"

    # TODO: verificar Redis cuando esté implementado
    # services["redis"] = "pendiente"

    all_ok = all(v == "ok" for v in services.values())
    return JSONResponse(
        status_code=200 if all_ok else 207,
        content={"status": "ok" if all_ok else "degraded", "services": services},
    )


# ─── Rutas de Órdenes (proxy completo) ────────────────────────────────────────
@app.api_route("/orders", methods=["GET", "POST"], tags=["Órdenes"])
@app.api_route("/orders/", methods=["GET", "POST"], tags=["Órdenes"])
async def orders_collection(request: Request):
    """Lista o crea órdenes → orders-api."""
    path = request.url.path
    return await forward(request, ORDERS_API_URL, path)


@app.api_route("/orders/{orden_id}", methods=["GET", "PUT", "DELETE"], tags=["Órdenes"])
async def orders_item(request: Request, orden_id: int):
    """Obtiene, actualiza o elimina una orden → orders-api."""
    return await forward(request, ORDERS_API_URL, f"/orders/{orden_id}")
