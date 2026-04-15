from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import settings


def normalize_database_url(raw_url: str) -> str:
    normalized = raw_url.strip()

    if normalized.startswith("postgres://"):
        normalized = normalized.replace("postgres://", "postgresql+asyncpg://", 1)
    if normalized.startswith("postgresql://"):
        normalized = normalized.replace("postgresql://", "postgresql+asyncpg://", 1)
    if normalized.startswith("postgresql+psycopg2://"):
        normalized = normalized.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)

    parts = urlsplit(normalized)
    db_name = parts.path.lstrip("/")

    if db_name.endswith("}") and "{" not in db_name:
        cleaned_name = db_name.rstrip("}")
        normalized = urlunsplit((parts.scheme, parts.netloc, f"/{cleaned_name}", parts.query, parts.fragment))
        parts = urlsplit(normalized)
        db_name = parts.path.lstrip("/")

    if "${" in normalized or "{" in db_name or "}" in db_name:
        raise ValueError(
            "DATABASE_URL parece invalida o con placeholders sin resolver. "
            f"Valor recibido: {normalized}"
        )

    return normalized


engine = create_async_engine(
    normalize_database_url(settings.database_url),
    echo=False,
    future=True,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def init_db() -> None:
    from .models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
