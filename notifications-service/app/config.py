from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # PostgreSQL — base de datos propia de notificaciones
    notifications_database_url: str = (
        "postgresql+asyncpg://notifications_user:notifications_pass"
        "@postgres-notifications:5432/notifications_db"
    )

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # RabbitMQ
    amqp_url: str = "amqp://guest:guest@rabbitmq:5672/"

    # EmailJS
    emailjs_service_id: str = ""
    emailjs_template_id: str = ""
    emailjs_public_key: str = ""
    emailjs_private_key: str = ""
    notification_to_email: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
