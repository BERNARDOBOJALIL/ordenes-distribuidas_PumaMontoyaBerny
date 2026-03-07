import redis.asyncio as aioredis
from .config import settings


async def get_redis() -> aioredis.Redis:
    """Retorna una conexión async a Redis usando la URL configurada."""
    return aioredis.from_url(settings.redis_url, decode_responses=True)
