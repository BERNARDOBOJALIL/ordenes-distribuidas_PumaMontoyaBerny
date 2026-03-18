import logging

from sqlalchemy.ext.asyncio import AsyncSession

from .models import Product
from .repositories.products_repo import product_count

logger = logging.getLogger("writer-service")

SEED_PRODUCTS = [
    Product(sku="LAPTOP-01",  name="Laptop Gamer",      description="Laptop gaming 16GB RAM, RTX 4060",     price=24999.99, stock=15),
    Product(sku="MONITOR-01", name="Monitor 27\" 4K",    description="Monitor IPS 27 pulgadas 4K 144Hz",    price=8499.00,  stock=30),
    Product(sku="TECLADO-01", name="Teclado Mecánico",   description="Teclado mecánico RGB switches Cherry", price=1899.50,  stock=50),
    Product(sku="MOUSE-01",   name="Mouse Inalámbrico",  description="Mouse ergonómico 16000 DPI wireless",  price=1299.00,  stock=40),
    Product(sku="AURICULAR-01", name="Audífonos BT",     description="Audífonos Bluetooth ANC 40h batería", price=2599.00,  stock=25),
    Product(sku="SSD-01",     name="SSD NVMe 1TB",       description="SSD M.2 NVMe Gen4 1TB lectura 7000MB/s", price=1799.00, stock=60),
    Product(sku="RAM-01",     name="RAM DDR5 16GB",      description="Módulo DDR5 16GB 5600MHz CL36",       price=1499.00,  stock=35),
    Product(sku="WEBCAM-01",  name="Webcam 1080p",       description="Webcam Full HD con micrófono y LED",  price=899.00,   stock=45),
    Product(sku="HUB-01",     name="Hub USB-C 7 en 1",   description="Hub USB-C: HDMI, USB3, SD, PD 100W",  price=749.00,   stock=55),
    Product(sku="CABLE-01",   name="Cable HDMI 2.1 2m",  description="Cable HDMI 2.1 8K 48Gbps 2 metros",  price=349.00,   stock=100),
]


async def seed_products_if_empty(session: AsyncSession) -> int:
    """Inserta productos de ejemplo solo si la tabla está vacía. Retorna la cantidad insertada."""
    count = await product_count(session)
    if count > 0:
        logger.info("[Seeder] Tabla products ya tiene %d registros, no se inserta nada.", count)
        return 0

    for p in SEED_PRODUCTS:
        session.add(p)

    await session.commit()
    logger.info("[Seeder] %d productos insertados.", len(SEED_PRODUCTS))
    return len(SEED_PRODUCTS)
