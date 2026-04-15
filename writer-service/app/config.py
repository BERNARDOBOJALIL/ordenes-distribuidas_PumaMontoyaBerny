from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Required from env (DATABASE_URL)
    database_url: str = Field(..., alias="DATABASE_URL")

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # RabbitMQ
    amqp_url: str = "amqp://guest:guest@rabbitmq:5672/%2F"
    rabbitmq_exchange: str = "orders.events"
    order_created_routing_key: str = "order.created"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
