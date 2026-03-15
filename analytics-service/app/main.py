import json
import logging
import time

import pika

from .config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] analytics-service: %(message)s",
)
logger = logging.getLogger("analytics-service")

metrics = {
    "orders_created_total": 0,
    "items_total": 0,
}


def handle_order_created(body: bytes) -> None:
    event = json.loads(body.decode("utf-8"))
    items = event.get("items", [])

    metrics["orders_created_total"] += 1
    metrics["items_total"] += sum(int(item.get("qty", 0)) for item in items)

    logger.info(
        "métrica registrada order_id=%s metrics=%s",
        event.get("order_id"),
        metrics,
    )


def run_consumer() -> None:
    while True:
        connection = None
        try:
            connection = pika.BlockingConnection(pika.URLParameters(settings.amqp_url))
            channel = connection.channel()

            channel.exchange_declare(
                exchange=settings.rabbitmq_exchange,
                exchange_type="topic",
                durable=True,
            )
            channel.queue_declare(queue=settings.analytics_queue, durable=True)
            channel.queue_bind(
                queue=settings.analytics_queue,
                exchange=settings.rabbitmq_exchange,
                routing_key=settings.order_created_routing_key,
            )
            channel.basic_qos(prefetch_count=10)

            logger.info(
                "consumiendo queue=%s routing_key=%s",
                settings.analytics_queue,
                settings.order_created_routing_key,
            )

            def on_message(ch, method, properties, body):
                try:
                    handle_order_created(body)
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as exc:
                    logger.error("error procesando mensaje: %s", exc)
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

            channel.basic_consume(queue=settings.analytics_queue, on_message_callback=on_message)
            channel.start_consuming()
        except Exception as exc:
            logger.error("conexion rabbitmq falló: %s. reintentando en 3s", exc)
            time.sleep(3)
        finally:
            if connection and connection.is_open:
                connection.close()


if __name__ == "__main__":
    run_consumer()
