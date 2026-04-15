from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
	database_url: str = Field(..., alias="DATABASE_URL")
	redis_url: str = "redis://redis:6379/0"

	internal_service_key: str = "change-me-internal-key"

	jwt_secret: str = "change-me-jwt-secret"
	jwt_algorithm: str = "HS256"
	jwt_access_token_minutes: int = 15
	jwt_refresh_token_days: int = 7

	default_admin_username: str = "admin"
	default_admin_email: str = "admin@example.com"
	default_admin_password: str = "ChangeMe123!"

	model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
