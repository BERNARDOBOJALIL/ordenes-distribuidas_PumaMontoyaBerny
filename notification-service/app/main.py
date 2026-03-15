import logging

from .services.consumer_service import run_consumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] notification-service: %(message)s",
)
logger = logging.getLogger("notification-service")


if __name__ == "__main__":
    run_consumer()
