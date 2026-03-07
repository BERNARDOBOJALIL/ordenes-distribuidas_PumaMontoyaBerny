from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    writer_service_url: str = "http://writer-service:8001"
    redis_url: str = "redis://redis:6379"
    queue_name: str = "orders_queue"
    http_timeout: float = 15.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
