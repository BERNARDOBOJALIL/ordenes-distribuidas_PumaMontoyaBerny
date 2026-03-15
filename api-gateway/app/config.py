from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    writer_service_url: str = "http://writer-service:8001"
    inventory_service_url: str = "http://inventory-service:8002"
    redis_url: str = "redis://redis:6379"
    writer_timeout_seconds: float = 1.0
    writer_max_retries: int = 1

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
