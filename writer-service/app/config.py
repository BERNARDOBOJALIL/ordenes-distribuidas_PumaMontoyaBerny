from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # PostgreSQL — asyncpg driver
    database_url: str = (
        "postgresql+asyncpg://orders_user:orders_pass@postgres:5432/orders_db"
    )

    # Redis
    redis_url: str = "redis://redis:6379/0"
    queue_name: str = "orders_queue"

    # Worker
    worker_interval: int = 10  # seconds between queue polls

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
