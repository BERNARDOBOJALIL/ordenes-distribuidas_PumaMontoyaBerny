import json
import logging
import threading
import time
from contextlib import asynccontextmanager

import pika
from fastapi import FastAPI

from .config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] inventory-service: %(message)s",
)
logger = logging.getLogger("inventory-service")

stock_by_sku: dict[str, int] = {}
stock_lock = threading.Lock()


def handle_order_created(body: bytes) -> None:
    event = json.loads(body.decode("utf-8"))
    order_id = event.get("order_id")
    items = event.get("items", [])

    for item in items:
        sku = item.get("sku")
        qty = int(item.get("qty", 0))
        if not sku or qty <= 0:
            continue
        with stock_lock:
            current_stock = stock_by_sku.get(sku, 100)
            stock_by_sku[sku] = current_stock - qty

    logger.info(
        "stock actualizado order_id=%s stock=%s",
        order_id,
        stock_by_sku,
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
            channel.queue_declare(queue=settings.inventory_queue, durable=True)
            channel.queue_bind(
                queue=settings.inventory_queue,
                exchange=settings.rabbitmq_exchange,
                routing_key=settings.order_created_routing_key,
            )
            channel.basic_qos(prefetch_count=10)

            logger.info(
                "consumiendo queue=%s routing_key=%s",
                settings.inventory_queue,
                settings.order_created_routing_key,
            )

            def on_message(ch, method, properties, body):
                try:
                    handle_order_created(body)
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as exc:
                    logger.error("error procesando mensaje: %s", exc)
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

            channel.basic_consume(queue=settings.inventory_queue, on_message_callback=on_message)
            channel.start_consuming()
        except Exception as exc:
            logger.error("conexion rabbitmq falló: %s. reintentando en 3s", exc)
            time.sleep(3)
        finally:
            if connection and connection.is_open:
                connection.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    consumer_thread = threading.Thread(target=run_consumer, daemon=True)
    consumer_thread.start()
    logger.info("inventory-service API up + consumer thread running")
    yield


app = FastAPI(
    title="Inventory Service",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    return {"service": "inventory-service", "status": "ok"}


@app.get("/internal/stock")
async def get_stock():
    with stock_lock:
        items = [{"sku": sku, "stock": qty} for sku, qty in sorted(stock_by_sku.items())]
    return {"items": items, "total_skus": len(items)}
