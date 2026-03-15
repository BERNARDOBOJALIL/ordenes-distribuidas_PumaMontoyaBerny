import logging
import threading

from ..schemas import OrderCreatedEvent, StockItem, StockResponse

logger = logging.getLogger("inventory-service")

_initial_stock = 100
_stock_by_sku: dict[str, int] = {}
_stock_lock = threading.Lock()


def apply_order_created(event: OrderCreatedEvent) -> None:
    for item in event.items:
        with _stock_lock:
            current_stock = _stock_by_sku.get(item.sku, _initial_stock)
            _stock_by_sku[item.sku] = current_stock - item.qty

    logger.info("stock actualizado order_id=%s stock=%s", event.order_id, _stock_by_sku)


def get_stock_snapshot() -> StockResponse:
    with _stock_lock:
        items = [
            StockItem(sku=sku, stock=qty)
            for sku, qty in sorted(_stock_by_sku.items())
        ]

    return StockResponse(items=items, total_skus=len(items))
