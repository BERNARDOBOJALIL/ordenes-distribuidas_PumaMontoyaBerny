import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User


async def get_user_by_identifier(session: AsyncSession, identifier: str) -> User | None:
    result = await session.execute(
        select(User).where(or_(User.username == identifier, User.email == identifier))
    )
    return result.scalar_one_or_none()


async def count_users(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(User))
    return result.scalar_one()


async def create_user(
    session: AsyncSession,
    username: str,
    email: str,
    password_hash: str,
) -> User:
    user = User(
        user_id=str(uuid.uuid4()),
        username=username,
        email=email,
        password_hash=password_hash,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user
