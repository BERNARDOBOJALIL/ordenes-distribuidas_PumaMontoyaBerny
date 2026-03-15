import logging

from ..schemas import OrderCreatedEvent

logger = logging.getLogger("analytics-service")

metrics = {
    "orders_created_total": 0,
    "items_total": 0,
}


def register_order_created(event: OrderCreatedEvent) -> None:
    metrics["orders_created_total"] += 1
    metrics["items_total"] += sum(item.qty for item in event.items)

    logger.info(
        "métrica registrada order_id=%s metrics=%s",
        event.order_id,
        metrics,
    )
