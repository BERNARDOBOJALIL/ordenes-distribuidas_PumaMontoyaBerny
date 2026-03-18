from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    amqp_url: str = "amqp://guest:guest@rabbitmq:5672/%2F"
    rabbitmq_exchange: str = "orders.events"
    order_created_routing_key: str = "order.created"
    notification_queue: str = "notification.order-created"

    # EmailJS
    emailjs_service_id: str = ""
    emailjs_template_id: str = ""
    emailjs_public_key: str = ""
    emailjs_private_key: str = ""
    notification_to_email: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
