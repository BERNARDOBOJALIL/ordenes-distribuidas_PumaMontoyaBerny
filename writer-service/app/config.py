from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # PostgreSQL — asyncpg driver
    database_url: str = (
        "postgresql+asyncpg://orders_user:orders_pass@postgres:5432/orders_db"
    )

    # Redis
    redis_url: str = "redis://redis:6379/0"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
