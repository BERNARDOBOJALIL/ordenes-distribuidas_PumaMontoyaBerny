"""
Repository layer for the Notification entity.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Notification


async def create_notification(
    session: AsyncSession,
    order_id: str,
    customer: str,
    event_type: str,
    message: str,
    reason: str | None = None,
) -> Notification:
    """Insert a new notification row and return it."""
    notification = Notification(
        order_id=order_id,
        customer=customer,
        event_type=event_type,
        message=message,
        reason=reason,
    )
    session.add(notification)
    await session.commit()
    await session.refresh(notification)
    return notification


async def get_all_notifications(session: AsyncSession) -> list[Notification]:
    """Return all notifications ordered by created_at descending."""
    result = await session.execute(
        select(Notification).order_by(Notification.created_at.desc())
    )
    return list(result.scalars().all())


async def get_notifications_by_order(
    session: AsyncSession, order_id: str
) -> list[Notification]:
    """Return all notifications for a specific order_id."""
    result = await session.execute(
        select(Notification)
        .where(Notification.order_id == order_id)
        .order_by(Notification.created_at.desc())
    )
    return list(result.scalars().all())
