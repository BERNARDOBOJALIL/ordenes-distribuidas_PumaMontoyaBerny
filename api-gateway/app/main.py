import logging
import uuid
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .schemas import (
    LoginRequest,
    LogoutRequest,
    MeResponse,
    OrderAccepted,
    OrderCreate,
    OrderStatus,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
)
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
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-Request-Id", "X-Service-Key"],
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    public_routes = {
        "/",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/auth/signup",
        "/auth/login",
        "/auth/refresh",
    }
    if request.url.path in public_routes:
        return await call_next(request)

    if request.method == "OPTIONS":
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "Falta token Bearer"})

    token = auth_header.split(" ", 1)[1].strip()
    try:
        verify_url = f"{settings.auth_service_url}/internal/auth/verify"
        verify_resp = await request.app.state.http.post(
            verify_url,
            json={"access_token": token},
            headers={"X-Service-Key": settings.internal_service_key},
            timeout=5.0,
        )
        if verify_resp.status_code == 401:
            return JSONResponse(status_code=401, content={"detail": "Token invalido o expirado"})
        verify_resp.raise_for_status()

        verify_data = verify_resp.json()
        request.state.user_id = verify_data["user_id"]
        request.state.username = verify_data["username"]
        request.state.access_token = token
    except httpx.HTTPStatusError:
        return JSONResponse(status_code=503, content={"detail": "Auth service no disponible"})
    except Exception:
        return JSONResponse(status_code=503, content={"detail": "Auth service no disponible"})

    return await call_next(request)


# ─── Gateway / Health ─────────────────────────────────────────────────────────
@app.get("/", tags=["Gateway"])
async def root():
    return {"gateway": "API Gateway activo", "version": "1.0.0", "docs": "/docs"}


@app.post("/auth/signup", response_model=TokenResponse, tags=["Auth"], summary="Registrar usuario")
async def signup(payload: SignupRequest):
    try:
        url = f"{settings.auth_service_url}/internal/auth/signup"
        resp = await app.state.http.post(
            url,
            json=payload.model_dump(),
            headers={"X-Service-Key": settings.internal_service_key},
            timeout=5.0,
        )
        if resp.status_code == 409:
            raise HTTPException(status_code=409, detail=resp.json().get("detail", "Usuario ya existe"))
        resp.raise_for_status()
        return resp.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Auth service no disponible: {exc}")


@app.post("/auth/login", response_model=TokenResponse, tags=["Auth"], summary="Login de usuario")
async def login(payload: LoginRequest):
    try:
        url = f"{settings.auth_service_url}/internal/auth/login"
        resp = await app.state.http.post(
            url,
            json=payload.model_dump(),
            headers={"X-Service-Key": settings.internal_service_key},
            timeout=5.0,
        )
        if resp.status_code == 401:
            raise HTTPException(status_code=401, detail="Credenciales invalidas")
        resp.raise_for_status()
        return resp.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Auth service no disponible: {exc}")


@app.post("/auth/refresh", response_model=TokenResponse, tags=["Auth"], summary="Renovar access token")
async def refresh_tokens(payload: RefreshRequest):
    try:
        url = f"{settings.auth_service_url}/internal/auth/refresh"
        resp = await app.state.http.post(
            url,
            json=payload.model_dump(),
            headers={"X-Service-Key": settings.internal_service_key},
            timeout=5.0,
        )
        if resp.status_code == 401:
            raise HTTPException(status_code=401, detail="Refresh token invalido o expirado")
        resp.raise_for_status()
        return resp.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Auth service no disponible: {exc}")


@app.post("/auth/logout", tags=["Auth"], summary="Cerrar sesion y revocar token")
async def logout(payload: LogoutRequest, request: Request):
    token = getattr(request.state, "access_token", "")
    if not token:
        raise HTTPException(status_code=401, detail="Token invalido")

    try:
        url = f"{settings.auth_service_url}/internal/auth/logout"
        resp = await app.state.http.post(
            url,
            json={"access_token": token, "refresh_token": payload.refresh_token},
            headers={"X-Service-Key": settings.internal_service_key},
            timeout=5.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Auth service no disponible: {exc}")


@app.get("/auth/me", response_model=MeResponse, tags=["Auth"], summary="Perfil del usuario autenticado")
async def me(request: Request):
    token = getattr(request.state, "access_token", "")
    if not token:
        raise HTTPException(status_code=401, detail="Token invalido")

    try:
        url = f"{settings.auth_service_url}/internal/auth/me"
        resp = await app.state.http.post(
            url,
            json={"access_token": token},
            headers={"X-Service-Key": settings.internal_service_key},
            timeout=5.0,
        )
        if resp.status_code == 401:
            raise HTTPException(status_code=401, detail="Token invalido o expirado")
        resp.raise_for_status()
        return resp.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Auth service no disponible: {exc}")


# ─── Ordenes ──────────────────────────────────────────────────────────────────
@app.post(
    "/orders",
    status_code=202,
    response_model=OrderAccepted,
    tags=["Ordenes"],
    summary="Crear orden (202 Accepted)",
)
async def crear_orden(orden: OrderCreate, request: Request):
    """
    1. Genera order_id (UUID) y X-Request-Id.
    2. HSET order:{id} status=RECEIVED en Redis.
    3. POST /internal/orders al writer-service (timeout 1 s, 1 retry).
    4. Si writer falla → HSET status=FAILED.
    5. Retorna 202 {order_id, status=RECEIVED}.
    """
    order_id = str(uuid.uuid4())
    user_id = request.state.user_id
    username = request.state.username
    items_dicts = [item.model_dump() for item in orden.items]

    await send_to_writer(
        app.state.http,
        app.state.redis,
        order_id=order_id,
        user_id=user_id,
        customer=username,
        items=items_dicts,
        service_key=settings.internal_service_key,
    )

    return OrderAccepted(order_id=order_id, status="RECEIVED")


@app.get(
    "/orders/{order_id}",
    response_model=OrderStatus,
    tags=["Ordenes"],
    summary="Consultar estado de una orden",
)
async def obtener_orden(order_id: str, request: Request):
    """Lee HGETALL order:{order_id} desde Redis y devuelve el estado."""
    data = await get_order_status(app.state.redis, order_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Orden {order_id} no encontrada en Redis")

    request_user_id = request.state.user_id
    if data.get("user_id") != request_user_id:
        raise HTTPException(status_code=404, detail=f"Orden {order_id} no encontrada")
    return data


@app.get(
    "/orders",
    tags=["Ordenes"],
    summary="Listar todas las órdenes (desde PostgreSQL vía writer-service)",
)
async def listar_ordenes(request: Request):
    """Proxy a GET /internal/orders del writer-service."""
    try:
        url = f"{settings.writer_service_url}/internal/orders"
        resp = await app.state.http.get(
            url,
            params={"user_id": request.state.user_id},
            headers={"X-Service-Key": settings.internal_service_key},
            timeout=5.0,
        )
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
        resp = await app.state.http.get(
            url,
            headers={"X-Service-Key": settings.internal_service_key},
            timeout=5.0,
        )
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
        resp = await app.state.http.get(
            url,
            headers={"X-Service-Key": settings.internal_service_key},
            timeout=5.0,
        )
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Producto {sku} no encontrado")
        resp.raise_for_status()
        return resp.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Writer service no disponible: {exc}")