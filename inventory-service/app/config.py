from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # PostgreSQL — asyncpg driver
    inventory_database_url: str = (
        "postgresql+asyncpg://inventory_user:inventory_pass@postgres-inventory:5432/inventory_db"
    )

    # Redis
    redis_url: str = "redis://redis:6379/0"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
