from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    amqp_url: str = "amqp://guest:guest@rabbitmq:5672/%2F"
    rabbitmq_exchange: str = "orders.events"
    order_created_routing_key: str = "order.created"
    inventory_queue: str = "inventory.order-created"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
