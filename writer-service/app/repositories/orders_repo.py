"""
Idempotent repository layer for the Order entity.

All functions receive an AsyncSession and operate exclusively through
SQLAlchemy ORM calls — no raw SQL strings.
"""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Order


async def upsert_order(
    session: AsyncSession,
    order_id: str,
    customer: str,
    items: list[dict],
) -> tuple[Order, bool]:
    """
    Idempotent insert: only creates the row if ``order_id`` does not exist.

    Returns (order, created) — *created* is False when the row already existed.
    """
    existing = await get_order(session, order_id)
    if existing:
        return existing, False

    order = Order(
        order_id=order_id,
        customer=customer,
        items=json.dumps(items),
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)
    return order, True


async def get_order(session: AsyncSession, order_id: str) -> Order | None:
    """Return an Order by primary key, or None if not found."""
    result = await session.execute(
        select(Order).where(Order.order_id == order_id)
    )
    return result.scalar_one_or_none()


async def get_all_orders(session: AsyncSession) -> list[Order]:
    """Return all orders ordered by created_at descending."""
    result = await session.execute(
        select(Order).order_by(Order.created_at.desc())
    )
    return list(result.scalars().all())