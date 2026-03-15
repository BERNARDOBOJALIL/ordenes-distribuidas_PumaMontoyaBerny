import logging

from ..schemas import OrderCreatedEvent

logger = logging.getLogger("notification-service")


def send_confirmation(event: OrderCreatedEvent) -> None:
    logger.info(
        "confirmación enviada customer=%s order_id=%s",
        event.customer,
        event.order_id,
    )
