"""
Inventory Service — product catalog & stock management.

Responsibilities
----------------
- GET  /internal/products          : list all products
- GET  /internal/products/{sku}    : get product by SKU
- POST /internal/products          : create a new product
- PUT  /internal/products/{sku}    : update a product
- POST /internal/stock/check       : check stock for a list of items
- POST /internal/stock/decrease    : decrease stock after order confirmed
- POST /internal/seed              : seed sample products
"""

import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Request

from .config import settings
from .db import AsyncSessionLocal, init_db
from .repositories.products_repo import (
    check_stock,
    create_product,
    decrease_stock,
    get_all_products,
    get_product,
    update_product,
)
from .schemas import (
    ProductCreate,
    ProductResponse,
    ProductUpdate,
    StockCheckRequest,
    StockCheckResponse,
    StockCheckResult,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("inventory-service")

SEED_PRODUCTS = [
    {"sku": "LAPTOP-01", "name": "Laptop Gamer 15", "description": "Laptop con RTX 4060, 16GB RAM", "price": 24999.99, "stock": 50},
    {"sku": "MOUSE-01", "name": "Mouse Inalámbrico", "description": "Mouse ergonómico Bluetooth", "price": 499.99, "stock": 200},
    {"sku": "SSD-01", "name": "SSD NVMe 1TB", "description": "Disco estado sólido PCIe Gen4", "price": 1899.99, "stock": 100},
    {"sku": "MONITOR-01", "name": "Monitor 27\" 4K", "description": "Monitor IPS 4K 60Hz", "price": 8999.99, "stock": 30},
    {"sku": "TECLADO-01", "name": "Teclado Mecánico RGB", "description": "Switches Cherry MX Red", "price": 1299.99, "stock": 150},
    {"sku": "RAM-01", "name": "RAM DDR5 32GB", "description": "Kit 2x16GB DDR5-5600", "price": 2499.99, "stock": 80},
    {"sku": "GPU-01", "name": "Tarjeta Gráfica RTX 4070", "description": "NVIDIA GeForce RTX 4070 12GB", "price": 12999.99, "stock": 25},
    {"sku": "CABLE-USB", "name": "Cable USB-C 2m", "description": "Cable USB-C a USB-C trenzado", "price": 149.99, "stock": 500},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    # Auto-seed products on first boot
    async with AsyncSessionLocal() as session:
        existing = await get_all_products(session)
        if not existing:
            for p in SEED_PRODUCTS:
                await create_product(session, **p)
            logger.info("[App] ✓ Seeded %d products.", len(SEED_PRODUCTS))
        else:
            logger.info("[App] Products table already has %d rows, skipping seed.", len(existing))

    logger.info("[App] DB tables ready. Redis connected.")
    yield
    await app.state.redis.aclose()
    logger.info("[App] Shutdown complete.")


app = FastAPI(
    title="Inventory Service – Productos",
    description="Servicio interno de catálogo de productos y gestión de stock.",
    version="1.0.0",
    lifespan=lifespan,
)


# ─── Health ───────────────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
async def root():
    return {"service": "inventory-service", "status": "ok", "version": "1.0.0"}


# ─── Products CRUD ────────────────────────────────────────────────────────────
@app.get(
    "/internal/products",
    response_model=list[ProductResponse],
    tags=["Products"],
    summary="Lista todos los productos",
)
async def list_products():
    async with AsyncSessionLocal() as session:
        products = await get_all_products(session)
    return [_product_to_dict(p) for p in products]


@app.get(
    "/internal/products/{sku}",
    response_model=ProductResponse,
    tags=["Products"],
    summary="Obtener producto por SKU",
)
async def get_product_by_sku(sku: str):
    async with AsyncSessionLocal() as session:
        product = await get_product(session, sku)
    if not product:
        raise HTTPException(status_code=404, detail=f"Producto {sku} no encontrado")
    return _product_to_dict(product)


@app.post(
    "/internal/products",
    status_code=201,
    response_model=ProductResponse,
    tags=["Products"],
    summary="Crear nuevo producto",
)
async def create_new_product(payload: ProductCreate):
    async with AsyncSessionLocal() as session:
        existing = await get_product(session, payload.sku)
        if existing:
            raise HTTPException(status_code=409, detail=f"Producto {payload.sku} ya existe")
        product = await create_product(session, **payload.model_dump())
    return _product_to_dict(product)


@app.put(
    "/internal/products/{sku}",
    response_model=ProductResponse,
    tags=["Products"],
    summary="Actualizar producto",
)
async def update_existing_product(sku: str, payload: ProductUpdate):
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No hay campos para actualizar")
    async with AsyncSessionLocal() as session:
        product = await update_product(session, sku, **updates)
    if not product:
        raise HTTPException(status_code=404, detail=f"Producto {sku} no encontrado")
    return _product_to_dict(product)


# ─── Stock operations ─────────────────────────────────────────────────────────
@app.post(
    "/internal/stock/check",
    response_model=StockCheckResponse,
    tags=["Stock"],
    summary="Verificar disponibilidad de stock",
)
async def check_stock_endpoint(payload: StockCheckRequest):
    items = [item.model_dump() for item in payload.items]
    async with AsyncSessionLocal() as session:
        results = await check_stock(session, items)
    all_available = all(r["sufficient"] for r in results)
    return StockCheckResponse(
        all_available=all_available,
        details=[StockCheckResult(**r) for r in results],
    )


@app.post(
    "/internal/stock/decrease",
    tags=["Stock"],
    summary="Descontar stock tras orden confirmada",
)
async def decrease_stock_endpoint(payload: StockCheckRequest):
    items = [item.model_dump() for item in payload.items]
    async with AsyncSessionLocal() as session:
        failed = []
        for item in items:
            ok = await decrease_stock(session, item["sku"], item["qty"])
            if not ok:
                failed.append(item["sku"])
    if failed:
        raise HTTPException(
            status_code=409,
            detail=f"Stock insuficiente para: {', '.join(failed)}",
        )
    return {"status": "ok", "message": "Stock descontado correctamente"}


# ─── Seed ─────────────────────────────────────────────────────────────────────
@app.post(
    "/internal/seed",
    tags=["Admin"],
    summary="Re-sembrar productos de ejemplo",
)
async def seed_products():
    async with AsyncSessionLocal() as session:
        created = 0
        for p in SEED_PRODUCTS:
            existing = await get_product(session, p["sku"])
            if not existing:
                await create_product(session, **p)
                created += 1
    return {"status": "ok", "created": created, "total_seed": len(SEED_PRODUCTS)}


def _product_to_dict(p) -> dict:
    return {
        "sku": p.sku,
        "name": p.name,
        "description": p.description,
        "price": p.price,
        "stock": p.stock,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }
