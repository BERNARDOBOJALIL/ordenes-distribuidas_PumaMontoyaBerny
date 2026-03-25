"""
Consumidor RabbitMQ para eventos de órdenes.
Escucha eventos 'order.created' y crea notificaciones.
"""

import json
import logging
from typing import Callable

import aio_pika
from aio_pika import IncomingMessage

from ..config import settings
from ..db import AsyncSessionLocal
from ..repositories.notifications_repo import create_notification
from .email_service import send_email_notification

logger = logging.getLogger("notifications-service")


class RabbitMQConsumer:
    """Consumidor asincrónico para eventos de órdenes de RabbitMQ."""

    def __init__(self):
        self.connection: aio_pika.Connection | None = None
        self.channel: aio_pika.Channel | None = None
        self.queue: aio_pika.Queue | None = None

    async def connect(self) -> None:
        """Conecta a RabbitMQ y declara exchange/cola."""
        try:
            self.connection = await aio_pika.connect_robust(settings.amqp_url)
            self.channel = await self.connection.channel()
            logger.info("[RabbitMQ] Conectado al broker")

            # Declara el exchange (si no existe)
            exchange = await self.channel.declare_exchange(
                name=settings.rabbitmq_exchange,
                type=aio_pika.ExchangeType.TOPIC,
                durable=True,
            )

            # Declara la cola para notificaciones
            self.queue = await self.channel.declare_queue(
                name=settings.notifications_queue_name,
                durable=True,
            )

            # Vincula la cola al exchange con routing keys
            await self.queue.bind(
                exchange=exchange,
                routing_key=settings.order_created_routing_key,
            )
            logger.info(
                f"[RabbitMQ] Cola '{settings.notifications_queue_name}' vinculada a "
                f"exchange '{settings.rabbitmq_exchange}' con routing key '{settings.order_created_routing_key}'"
            )

        except Exception as exc:
            logger.error(f"[RabbitMQ] Fallo de conexión: {exc}")
            raise

    async def start_consuming(self, on_message: Callable) -> None:
        """Inicia a consumir mensajes de la cola."""
        if not self.queue:
            raise RuntimeError("Cola no inicializada. Llama a connect() primero.")

        logger.info("[RabbitMQ] Iniciando consumidor...")
        async with self.queue.iterator() as queue_iter:
            async for message in queue_iter:
                try:
                    await on_message(message)
                    await message.ack()
                except Exception as exc:
                    logger.error(f"[RabbitMQ] Error procesando mensaje: {exc}")
                    await message.nack(requeue=True)

    async def close(self) -> None:
        """Cierra la conexión de RabbitMQ."""
        if self.connection:
            await self.connection.close()
            logger.info("[RabbitMQ] Conexión cerrada")


async def handle_order_created_event(message: IncomingMessage) -> None:
    """
    Procesa evento order.created desde RabbitMQ.
    
    Estructura esperada del mensaje:
    {
        "order_id": "UUID",
        "customer": "Nombre",
        "items": [{"sku": "...", "qty": ...}],
        "timestamp": "string ISO8601"
    }
    """
    try:
        payload = json.loads(message.body.decode())
        
        order_id = payload.get("order_id")
        customer = payload.get("customer")
        items = payload.get("items", [])
        
        logger.info(
            "[RabbitMQ] Evento order.created recibido: order_id=%s, customer=%s",
            order_id,
            customer,
        )

        # Persiste la notificación en PostgreSQL
        async with AsyncSessionLocal() as session:
            notification = await create_notification(
                session,
                order_id=order_id,
                customer=customer,
                event_type="order.created",
                message="Orden creada exitosamente",
                reason="Recibida desde RabbitMQ",
            )

        logger.info(
            "[RabbitMQ] ✓ Notificación persistida (id=%d) para order_id=%s",
            notification.id,
            order_id,
        )

        # Envía email (sin bloquear, fire-and-forget)
        try:
            await send_email_notification(
                order_id=order_id,
                customer=customer,
                event_type="order.created",
                message="Orden creada exitosamente",
                items=items,
            )
            logger.info("[RabbitMQ] ✓ Email enviado para order_id=%s", order_id)
        except Exception as exc:
            logger.warning(
                "[RabbitMQ] ⚠ Fallo al enviar email para order_id=%s: %s",
                order_id,
                exc,
            )

    except json.JSONDecodeError as exc:
        logger.error("[RabbitMQ] JSON inválido en mensaje: %s", exc)
        raise
    except KeyError as exc:
        logger.error("[RabbitMQ] Campo requerido faltante en mensaje: %s", exc)
        raise
