import logging

from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .repositories.users_repo import count_users, create_user
from .security import hash_password

logger = logging.getLogger("auth-service")


async def seed_default_user_if_empty(session: AsyncSession) -> int:
    existing_users = await count_users(session)
    if existing_users > 0:
        logger.info("[Seeder] Tabla users ya tiene %d registros, no se inserta usuario default.", existing_users)
        return 0

    await create_user(
        session,
        username=settings.default_admin_username,
        email=settings.default_admin_email,
        password_hash=hash_password(settings.default_admin_password),
    )
    logger.info("[Seeder] Usuario default creado: %s", settings.default_admin_username)
    return 1
