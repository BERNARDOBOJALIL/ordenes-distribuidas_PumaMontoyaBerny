"""
Repository layer for the Product entity.
"""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Product


async def get_product(session: AsyncSession, sku: str) -> Product | None:
    result = await session.execute(select(Product).where(Product.sku == sku))
    return result.scalar_one_or_none()


async def get_all_products(session: AsyncSession) -> list[Product]:
    result = await session.execute(select(Product).order_by(Product.sku))
    return list(result.scalars().all())


async def create_product(session: AsyncSession, **kwargs) -> Product:
    product = Product(**kwargs)
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product


async def update_product(session: AsyncSession, sku: str, **kwargs) -> Product | None:
    product = await get_product(session, sku)
    if not product:
        return None
    for key, value in kwargs.items():
        if value is not None:
            setattr(product, key, value)
    await session.commit()
    await session.refresh(product)
    return product


async def decrease_stock(session: AsyncSession, sku: str, qty: int) -> bool:
    """Atomically decrease stock. Returns False if insufficient stock."""
    product = await get_product(session, sku)
    if not product or product.stock < qty:
        return False
    product.stock -= qty
    await session.commit()
    return True


async def check_stock(session: AsyncSession, items: list[dict]) -> list[dict]:
    """Check stock availability for a list of {sku, qty} items."""
    results = []
    for item in items:
        product = await get_product(session, item["sku"])
        available = product.stock if product else 0
        results.append({
            "sku": item["sku"],
            "requested": item["qty"],
            "available": available,
            "sufficient": available >= item["qty"],
        })
    return results
