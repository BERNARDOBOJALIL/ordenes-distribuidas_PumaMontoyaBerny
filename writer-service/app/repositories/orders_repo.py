"""
Idempotent repository layer for the Order entity.

All functions receive an AsyncSession and operate exclusively through
SQLAlchemy ORM calls — no raw SQL strings.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Order


async def upsert_order(session: AsyncSession, data: dict) -> Order:
    """
    Persist a new order.

    For queue-based ingestion the api-gateway does not assign an order ID
    before enqueueing, so each payload always produces a new row.  The
    function is named 'upsert' to leave room for an idempotency check if a
    caller ever passes an explicit ``id`` in *data*.
    """
    # If an explicit id is provided, skip insertion when the row already exists
    if "id" in data and data["id"] is not None:
        existing = await get_order(session, data["id"])
        if existing:
            return existing

    order = Order(**data)
    session.add(order)
    await session.commit()
    await session.refresh(order)
    return order


async def get_order(session: AsyncSession, order_id: int) -> Order | None:
    """Return an Order by primary key, or None if not found."""
    result = await session.execute(select(Order).where(Order.id == order_id))
    return result.scalar_one_or_none()


async def list_orders(
    session: AsyncSession,
    skip: int = 0,
    limit: int = 100,
) -> list[Order]:
    """Return a paginated list of all orders."""
    result = await session.execute(select(Order).offset(skip).limit(limit))
    return list(result.scalars().all())


async def update_order(
    session: AsyncSession,
    order_id: int,
    changes: dict,
) -> Order | None:
    """Apply *changes* to an existing order and return the updated instance."""
    order = await get_order(session, order_id)
    if not order:
        return None
    for field, value in changes.items():
        setattr(order, field, value)
    await session.commit()
    await session.refresh(order)
    return order


async def delete_order(session: AsyncSession, order_id: int) -> bool:
    """Delete an order by ID. Returns True if the row existed, False otherwise."""
    order = await get_order(session, order_id)
    if not order:
        return False
    await session.delete(order)
    await session.commit()
    return True
