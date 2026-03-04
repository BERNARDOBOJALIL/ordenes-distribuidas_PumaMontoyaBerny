from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime
import asyncio
import json
import os
import time
import redis.asyncio as aioredis

# ─── Base de datos (PostgreSQL) ───────────────────────────────────────────────
DB_USER     = os.getenv("POSTGRES_USER",     "ordenes_user")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "ordenes_pass")
DB_HOST     = os.getenv("POSTGRES_HOST",     "db")
DB_PORT     = os.getenv("POSTGRES_PORT",     "5432")
DB_NAME     = os.getenv("POSTGRES_DB",       "ordenes_db")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

def create_engine_with_retry(url: str, retries: int = 10, delay: int = 3):
    for attempt in range(retries):
        try:
            eng = create_engine(url, pool_pre_ping=True)
            eng.connect()
            return eng
        except Exception as exc:
            print(f"[DB] Intento {attempt + 1}/{retries} fallido: {exc}")
            time.sleep(delay)
    raise RuntimeError("No se pudo conectar a PostgreSQL después de varios intentos")

engine = create_engine_with_retry(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ─── Modelo ORM 
class OrderDB(Base):
    __tablename__ = "orders"

    id          = Column(Integer, primary_key=True, index=True)
    cliente     = Column(String, nullable=False)
    producto    = Column(String, nullable=False)
    cantidad    = Column(Integer, nullable=False)
    precio      = Column(Float, nullable=False)
    estado      = Column(String, default="pendiente")   # pendiente | en_proceso | completado | cancelado
    creado_en   = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)


# ─── Schemas Pydantic 
class OrderCreate(BaseModel):
    cliente:  str
    producto: str
    cantidad: int
    precio:   float
    estado:   Optional[str] = "pendiente"


class OrderUpdate(BaseModel):
    cliente:  Optional[str]  = None
    producto: Optional[str]  = None
    cantidad: Optional[int]  = None
    precio:   Optional[float]= None
    estado:   Optional[str]  = None


class OrderResponse(BaseModel):
    id:         int
    cliente:    str
    producto:   str
    cantidad:   int
    precio:     float
    estado:     str
    creado_en:  datetime

    class Config:
        from_attributes = True


# ─── Dependencia DB 
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─── Config Redis ────────────────────────────────────────────────────────────
REDIS_URL       = os.getenv("REDIS_URL", "redis://redis:6379")
QUEUE_NAME      = "orders_queue"
WORKER_INTERVAL = int(os.getenv("WORKER_INTERVAL", "10"))  # segundos


# ─── Worker: consume la cola Redis y guarda en PostgreSQL ────────────────────
async def redis_worker():
    """Corre en background. Saca órdenes de Redis y las persiste en PostgreSQL."""
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    print(f"[WORKER] Iniciado. Revisando cola '{QUEUE_NAME}' cada {WORKER_INTERVAL}s")
    while True:
        await asyncio.sleep(WORKER_INTERVAL)
        try:
            raw = await r.rpop(QUEUE_NAME)
            if raw is None:
                print(f"[WORKER] Cola vacía, esperando {WORKER_INTERVAL}s más...")
                continue

            datos = json.loads(raw)
            print(f"[WORKER] Procesando orden: {datos}")

            db = SessionLocal()
            try:
                # Forzar estado a 'procesado' al salir de la cola
                datos["estado"] = "procesado"
                nueva = OrderDB(**datos)
                db.add(nueva)
                db.commit()
                db.refresh(nueva)
                print(f"[WORKER] ✓ Orden guardada — ID={nueva.id}, cliente={nueva.cliente}")
            except Exception as db_err:
                db.rollback()
                print(f"[WORKER] Error al guardar en DB: {db_err}")
                # Devolver a la cola para no perder la orden
                await r.rpush(QUEUE_NAME, raw)
            finally:
                db.close()

        except Exception as err:
            print(f"[WORKER] Error inesperado: {err}")


# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Órdenes API",
    description="Microservicio de órdenes — consume cola Redis y persiste en PostgreSQL",
    version="2.0.0",
)


@app.on_event("startup")
async def startup():
    asyncio.create_task(redis_worker())
    print("[App] Worker Redis iniciado en background")


# ─── Endpoints

@app.get("/", tags=["Root"])
def root():
    return {"message": "API de Órdenes funcionando ✓"}


@app.post("/orders/", response_model=OrderResponse, status_code=201, tags=["Órdenes"])
def crear_orden(orden: OrderCreate, db: Session = Depends(get_db)):
    """Crear una nueva orden."""
    nueva = OrderDB(**orden.model_dump())
    db.add(nueva)
    db.commit()
    db.refresh(nueva)
    return nueva


@app.get("/orders/", response_model=List[OrderResponse], tags=["Órdenes"])
def listar_ordenes(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """Listar todas las órdenes."""
    return db.query(OrderDB).offset(skip).limit(limit).all()


@app.get("/orders/{orden_id}", response_model=OrderResponse, tags=["Órdenes"])
def obtener_orden(orden_id: int, db: Session = Depends(get_db)):
    """Obtener una orden por ID."""
    orden = db.query(OrderDB).filter(OrderDB.id == orden_id).first()
    if not orden:
        raise HTTPException(status_code=404, detail=f"Orden {orden_id} no encontrada")
    return orden


@app.put("/orders/{orden_id}", response_model=OrderResponse, tags=["Órdenes"])
def actualizar_orden(orden_id: int, datos: OrderUpdate, db: Session = Depends(get_db)):
    """Actualizar una orden existente (campos opcionales)."""
    orden = db.query(OrderDB).filter(OrderDB.id == orden_id).first()
    if not orden:
        raise HTTPException(status_code=404, detail=f"Orden {orden_id} no encontrada")

    cambios = datos.model_dump(exclude_unset=True)
    for campo, valor in cambios.items():
        setattr(orden, campo, valor)

    db.commit()
    db.refresh(orden)
    return orden


@app.delete("/orders/{orden_id}", tags=["Órdenes"])
def eliminar_orden(orden_id: int, db: Session = Depends(get_db)):
    """Eliminar una orden por ID."""
    orden = db.query(OrderDB).filter(OrderDB.id == orden_id).first()
    if not orden:
        raise HTTPException(status_code=404, detail=f"Orden {orden_id} no encontrada")
    db.delete(orden)
    db.commit()
    return {"detail": f"Orden {orden_id} eliminada correctamente"}
