import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .schemas import StockResponse
from .services.consumer_service import run_consumer
from .services.stock_service import get_stock_snapshot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] inventory-service: %(message)s",
)
logger = logging.getLogger("inventory-service")


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


@app.get("/internal/stock", response_model=StockResponse)
async def get_stock() -> StockResponse:
    return get_stock_snapshot()
