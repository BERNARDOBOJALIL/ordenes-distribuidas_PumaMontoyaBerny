from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    writer_service_url: str = "http://writer-service:7001"
    auth_service_url: str = "http://auth-service:7000"
    inventory_service_url: str = "http://inventory-service:8002"
    redis_url: str = "redis://redis:6379"
    writer_timeout_seconds: float = 1.0
    writer_max_retries: int = 1
    internal_service_key: str = "change-me-internal-key"

    cors_allow_origins: str = "http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


settings = Settings()
