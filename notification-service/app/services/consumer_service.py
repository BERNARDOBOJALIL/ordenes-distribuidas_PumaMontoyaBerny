import json
import logging
import time

import pika
from pydantic import ValidationError

from ..config import settings
from ..schemas import OrderCreatedEvent
from .notification_service import send_confirmation

logger = logging.getLogger("notification-service")


def handle_order_created_message(body: bytes) -> None:
    payload = json.loads(body.decode("utf-8"))
    event = OrderCreatedEvent.model_validate(payload)
    send_confirmation(event)


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
            channel.queue_declare(queue=settings.notification_queue, durable=True)
            channel.queue_bind(
                queue=settings.notification_queue,
                exchange=settings.rabbitmq_exchange,
                routing_key=settings.order_created_routing_key,
            )
            channel.basic_qos(prefetch_count=10)

            logger.info(
                "consumiendo queue=%s routing_key=%s",
                settings.notification_queue,
                settings.order_created_routing_key,
            )

            def on_message(ch, method, properties, body):
                try:
                    handle_order_created_message(body)
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except ValidationError as exc:
                    logger.error("mensaje inválido (pydantic): %s", exc)
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as exc:
                    logger.error("error procesando mensaje: %s", exc)
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

            channel.basic_consume(
                queue=settings.notification_queue,
                on_message_callback=on_message,
            )
            channel.start_consuming()
        except Exception as exc:
            logger.error("conexion rabbitmq falló: %s. reintentando en 3s", exc)
            time.sleep(3)
        finally:
            if connection and connection.is_open:
                connection.close()
