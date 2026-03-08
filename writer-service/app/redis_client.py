import redis.asyncio as aioredis

from .config import settings


def get_redis_client() -> aioredis.Redis:
    """Return a connected async Redis client (call .aclose() when done)."""
    return aioredis.from_url(settings.redis_url, decode_responses=True)
