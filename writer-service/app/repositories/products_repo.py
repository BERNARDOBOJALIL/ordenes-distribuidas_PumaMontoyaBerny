import logging

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Product

logger = logging.getLogger("writer-service")


async def get_all_products(session: AsyncSession) -> list[Product]:
    result = await session.execute(
        select(Product).order_by(Product.sku)
    )
    return list(result.scalars().all())


async def get_product_by_sku(session: AsyncSession, sku: str) -> Product | None:
    result = await session.execute(
        select(Product).where(Product.sku == sku)
    )
    return result.scalar_one_or_none()


async def product_count(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(Product))
    return result.scalar_one()


async def validate_stock(session: AsyncSession, items: list[dict]) -> None:
    """
    Valida que cada SKU exista y tenga stock suficiente.
    Lanza ValueError con detalle por cada problema encontrado.
    """
    errors = []
    for item in items:
        sku = item["sku"]
        qty = item["qty"]

        if qty <= 0:
            errors.append(f"SKU '{sku}': la cantidad debe ser mayor a 0 (recibido: {qty})")
            continue

        product = await get_product_by_sku(session, sku)
        if product is None:
            errors.append(f"SKU '{sku}' no existe en el catálogo de productos")
            continue

        if product.stock <= 0:
            errors.append(f"SKU '{sku}' sin existencias (stock: 0)")
        elif qty > product.stock:
            errors.append(
                f"SKU '{sku}': solicitado {qty}, disponible {product.stock}"
            )

    if errors:
        raise ValueError(errors)


async def reduce_stock(session: AsyncSession, items: list[dict]) -> list[dict]:
    """
    Descuenta el stock de cada SKU en `items`.
    Retorna lista de advertencias si algún SKU no existe o stock queda negativo.
    """
    warnings = []
    for item in items:
        sku = item["sku"]
        qty = item["qty"]
        product = await get_product_by_sku(session, sku)
        if product is None:
            logger.warning("[reduce_stock] SKU=%s no existe en productos", sku)
            warnings.append({"sku": sku, "warning": "SKU no encontrado en catálogo"})
            continue
        new_stock = product.stock - qty
        if new_stock < 0:
            logger.warning(
                "[reduce_stock] SKU=%s stock insuficiente (actual=%d, pedido=%d)",
                sku, product.stock, qty,
            )
            warnings.append({"sku": sku, "warning": f"Stock insuficiente (disponible: {product.stock})"})
            new_stock = 0
        await session.execute(
            update(Product).where(Product.sku == sku).values(stock=new_stock)
        )
        logger.info("[reduce_stock] SKU=%s stock %d → %d", sku, product.stock, new_stock)
    await session.commit()
    return warnings
