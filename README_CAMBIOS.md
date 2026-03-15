# Documentación de Cambios — Arquitectura Event-Driven con RabbitMQ

Este documento explica **todo lo que cambió** en el sistema distribuido de órdenes cuando se añadió la arquitectura orientada a eventos. Se parte del sistema original (API Gateway + Writer Service + Postgres + Redis) y se llega al sistema actual con RabbitMQ + 3 consumidores + frontend visual.

---

## Tabla de Contenidos

1. [¿Qué había antes?](#1-qué-había-antes)
2. [¿Qué hay ahora?](#2-qué-hay-ahora)
3. [El flujo completo paso a paso](#3-el-flujo-completo-paso-a-paso)
4. [Cambios por archivo](#4-cambios-por-archivo)
   - [docker-compose.yml](#41-docker-composeyml)
   - [.env](#42-env)
   - [writer-service → order-service](#43-writer-service--order-service-appmainsky)
   - [writer-service config.py](#44-writer-service-appconfigpy)
   - [writer-service requirements.txt](#45-writer-service-requirementstxt)
   - [api-gateway config.py](#46-api-gateway-appconfigpy)
   - [api-gateway main.py](#47-api-gateway-appmainsky)
   - [inventory-service (nuevo)](#48-inventory-service-nuevo)
   - [notification-service (nuevo)](#49-notification-service-nuevo)
   - [analytics-service (nuevo)](#410-analytics-service-nuevo)
   - [Frontend index.html](#411-frontend-indexhtml)
5. [Topología RabbitMQ](#5-topología-rabbitmq)
6. [Nuevas variables de entorno](#6-nuevas-variables-de-entorno)
7. [Nuevos endpoints](#7-nuevos-endpoints)
8. [Cómo levantar el sistema](#8-cómo-levantar-el-sistema)
9. [Cómo validar que todo funciona](#9-cómo-validar-que-todo-funciona)
10. [Diagrama de arquitectura completo](#10-diagrama-de-arquitectura-completo)

---

## 1. ¿Qué había antes?

El sistema original tenía **4 servicios**:

```
Cliente → api-gateway (:8000) → writer-service (HTTP POST síncrono)
                ↓                       ↓
             Redis                   Postgres
```

El flujo era completamente **síncrono**: el API Gateway esperaba la respuesta del writer-service antes de contestar al cliente. Si el writer fallaba, el API Gateway reintentaba una vez y después marcaba la orden como `FAILED`.

No existía comunicación asíncrona, ni eventos, ni servicios de inventario, notificaciones o analíticas.

---

## 2. ¿Qué hay ahora?

El sistema ahora tiene **9 servicios**:

| Servicio               | Puerto  | Rol |
|------------------------|---------|-----|
| `api-gateway`          | 8000    | Punto de entrada HTTP público |
| `order-service`        | 8001    | Persiste órdenes + publica eventos |
| `postgres`             | 5432    | Base de datos relacional |
| `redis`                | 6379    | Cache de estado de órdenes |
| `rabbitmq`             | 5672 / 15672 | Broker de mensajes (+ UI web) |
| `inventory-service`    | 8002 (interno) | Descuenta stock al recibir evento |
| `notification-service` | —       | Envía confirmación al recibir evento |
| `analytics-service`    | —       | Registra métricas al recibir evento |
| `frontend`             | 3000    | Interfaz visual SPA |

El flujo ahora combina **comunicación síncrona** (HTTP) para la respuesta inmediata al cliente y **comunicación asíncrona** (RabbitMQ) para los efectos secundarios (inventario, notificación, analítica).

---

## 3. El flujo completo paso a paso

```
Cliente
  │
  │  POST /orders  {customer, items}
  ▼
api-gateway (:8000)
  │  ① Genera order_id (UUID) + X-Request-Id
  │  ② HSET order:{id}  status=RECEIVED  → Redis
  │  ③ HTTP POST /internal/orders  (timeout 1s, 1 retry)
  ▼
order-service (:8001)
  │  ④ upsert_order() → inserta en PostgreSQL si no existe
  │  ⑤ HSET order:{id}  status=PERSISTED  → Redis
  │  ⑥ publish_order_created_event() → RabbitMQ
  │       exchange: orders.events
  │       routing_key: order.created
  │       body: { event_type, order_id, customer, items, created_at, request_id }
  ▼
RabbitMQ — exchange: orders.events  (tipo: topic)
  │
  ├──► queue: inventory.order-created
  │         ▼
  │    inventory-service
  │         Descuenta qty de cada ítem en stock_by_sku{}
  │         stock inicial = 100 por SKU desconocido
  │         Expone GET /internal/stock con el estado actual
  │
  ├──► queue: notification.order-created
  │         ▼
  │    notification-service
  │         Registra en log: "confirmación enviada customer=X order_id=Y"
  │         (simula envío de email/SMS)
  │
  └──► queue: analytics.order-created
            ▼
       analytics-service
            Incrementa: orders_created_total += 1
                        items_total += sum(qty de todos los ítems)
            Registra métrica en el log


api-gateway (:8000)  ←  responde 202 Accepted {order_id, status=RECEIVED}
  │
  └──► GET /inventory/stock  →  proxy a inventory-service/internal/stock
```

**Puntos clave del diseño:**
- La respuesta al cliente (202 Accepted) llega **antes** de que RabbitMQ entregue los eventos a los consumidores.
- Los tres consumidores reciben el mismo evento de forma **independiente** (cada uno tiene su propia queue vinculada al mismo exchange).
- Si un consumidor falla, el mensaje se reencola (`basic_nack + requeue=True`).
- Si RabbitMQ cae, la queue y el exchange son **durable=True**, por lo que los mensajes no se pierden.

---

## 4. Cambios por archivo

### 4.1 `docker-compose.yml`

**Antes:** 4 servicios (`api-gateway`, `writer-service`, `postgres`, `redis`).

**Ahora:** 9 servicios. Los cambios concretos:

```yaml
# NUEVO — RabbitMQ con UI de administración
rabbitmq:
  image: rabbitmq:3-management
  ports:
    - "5672:5672"    # AMQP
    - "15672:15672"  # UI web (usuario: guest / contraseña: guest)
  healthcheck:
    test: ["CMD", "rabbitmq-diagnostics", "-q", "ping"]
    interval: 5s
    retries: 10
```

```yaml
# RENOMBRADO: writer-service → order-service
# El código fuente sigue en ./writer-service pero el contenedor se llama order-service
order-service:
  build: ./writer-service    # <- misma carpeta de código
  ports:
    - "8001:8001"
  depends_on:
    postgres:   { condition: service_healthy }
    redis:      { condition: service_healthy }
    rabbitmq:   { condition: service_healthy }  # <- dependencia nueva
```

```yaml
# NUEVO — inventory-service (FastAPI + pika consumer en thread)
inventory-service:
  build: ./inventory-service
  env_file: .env
  depends_on:
    rabbitmq: { condition: service_healthy }

# NUEVO — notification-service (script pika puro)
notification-service:
  build: ./notification-service
  env_file: .env
  depends_on:
    rabbitmq: { condition: service_healthy }

# NUEVO — analytics-service (script pika puro)
analytics-service:
  build: ./analytics-service
  env_file: .env
  depends_on:
    rabbitmq: { condition: service_healthy }
```

```yaml
# NUEVO — frontend SPA servida con nginx
frontend:
  build: ./Frontend
  ports:
    - "3000:80"
  depends_on:
    - api-gateway
```

---

### 4.2 `.env`

Se añadieron las variables de RabbitMQ y los nombres de las queues:

```diff
  WRITER_SERVICE_URL=http://order-service:8001
+ INVENTORY_SERVICE_URL=http://inventory-service:8002

+ AMQP_URL=amqp://guest:guest@rabbitmq:5672/%2F
+ RABBITMQ_EXCHANGE=orders.events
+ ORDER_CREATED_ROUTING_KEY=order.created

+ INVENTORY_QUEUE=inventory.order-created
+ NOTIFICATION_QUEUE=notification.order-created
+ ANALYTICS_QUEUE=analytics.order-created
```

---

### 4.3 `writer-service` / `order-service` — `app/main.py`

Este es el archivo con **más cambios**. Se añadió la lógica de publicación de eventos.

#### Función nueva: `publish_order_created_event(event: dict)`

```python
def publish_order_created_event(event: dict) -> None:
    """Blocking publisher using pika; run this inside asyncio.to_thread()."""
    params = pika.URLParameters(settings.amqp_url)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()

    channel.exchange_declare(
        exchange=settings.rabbitmq_exchange,   # "orders.events"
        exchange_type="topic",
        durable=True,
    )

    channel.basic_publish(
        exchange=settings.rabbitmq_exchange,
        routing_key=settings.order_created_routing_key,  # "order.created"
        body=json.dumps(event),
        properties=pika.BasicProperties(
            content_type="application/json",
            delivery_mode=2,   # persistente en disco (no se pierde si RabbitMQ se reinicia)
        ),
    )
    connection.close()
```

**¿Por qué `asyncio.to_thread()`?**
FastAPI usa un event loop de asyncio. La librería `pika` es **bloqueante** (síncrona). Si se llama directamente a `pika.BlockingConnection` dentro de una corutina async, bloquearía todo el event loop. La solución es ejecutar la función pika en un hilo del pool de threads con `asyncio.to_thread()`.

#### Cambio en el endpoint `POST /internal/orders`

```python
# Antes: solo insertaba en Postgres y actualizaba Redis
# Ahora: además publica el evento si la orden es nueva
if created:
    event = {
        "event_type": "order.created",
        "order_id": payload.order_id,
        "customer": payload.customer,
        "items": [item.model_dump() for item in payload.items],
        "created_at": order.created_at.isoformat(),
        "request_id": request_id,
    }
    await asyncio.to_thread(publish_order_created_event, event)
```

**Idempotencia conservada:** el evento solo se publica si `created=True`, es decir, si la orden fue insertada por primera vez. Si es un reintento del API Gateway con el mismo `order_id`, no se vuelve a publicar.

---

### 4.4 `writer-service` — `app/config.py`

Se añadieron 3 nuevas variables de configuración para RabbitMQ:

```python
# Antes
class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://..."
    redis_url: str = "redis://redis:6379/0"

# Ahora
class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://..."
    redis_url: str = "redis://redis:6379/0"
    # NUEVAS
    amqp_url: str = "amqp://guest:guest@rabbitmq:5672/%2F"
    rabbitmq_exchange: str = "orders.events"
    order_created_routing_key: str = "order.created"
```

---

### 4.5 `writer-service` — `requirements.txt`

```diff
  fastapi>=0.111,<1
  uvicorn[standard]>=0.29,<1
  sqlalchemy[asyncio]>=2.0,<3
  asyncpg>=0.29,<1
  redis>=5,<6
  pydantic-settings>=2,<3
+ pika>=1.3,<2
```

`pika` es la librería oficial de RabbitMQ para Python (cliente AMQP 0-9-1).

---

### 4.6 `api-gateway` — `app/config.py`

Se añadió la URL del nuevo `inventory-service`:

```python
# Antes
class Settings(BaseSettings):
    writer_service_url: str = "http://writer-service:8001"
    redis_url: str = "redis://redis:6379"
    writer_timeout_seconds: float = 1.0
    writer_max_retries: int = 1

# Ahora
class Settings(BaseSettings):
    writer_service_url: str = "http://writer-service:8001"
    inventory_service_url: str = "http://inventory-service:8002"  # NUEVA
    redis_url: str = "redis://redis:6379"
    writer_timeout_seconds: float = 1.0
    writer_max_retries: int = 1
```

---

### 4.7 `api-gateway` — `app/main.py`

Se añadió un nuevo endpoint proxy para exponer el stock al exterior:

```python
# NUEVO endpoint
@app.get(
    "/inventory/stock",
    tags=["Inventory"],
    summary="Consultar stock actual desde inventory-service",
)
async def get_inventory_stock():
    """Proxy a GET /internal/stock del inventory-service."""
    try:
        url = f"{settings.inventory_service_url}/internal/stock"
        resp = await app.state.http.get(url, timeout=5.0)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Inventory service no disponible: {exc}")
```

**¿Por qué un proxy?** El `inventory-service` no expone puerto al host, solo es accesible dentro de la red Docker. El `api-gateway` es el único punto de entrada y actúa como proxy hacia los servicios internos.

---

### 4.8 `inventory-service` (nuevo)

Este servicio es completamente nuevo. Fue diseñado como **FastAPI + consumidor pika en un hilo separado**.

#### Estructura

```
inventory-service/
├── Dockerfile
├── requirements.txt
└── app/
    ├── __init__.py
    ├── config.py
    └── main.py
```

#### `app/config.py`

```python
class Settings(BaseSettings):
    amqp_url: str = "amqp://guest:guest@rabbitmq:5672/%2F"
    rabbitmq_exchange: str = "orders.events"
    order_created_routing_key: str = "order.created"
    inventory_queue: str = "inventory.order-created"
```

#### `app/main.py` — funciones clave

| Función / Variable | Descripción |
|---|---|
| `stock_by_sku: dict[str, int]` | Diccionario en memoria: `{sku: stock_actual}`. Stock inicial = 100 por SKU nuevo. |
| `stock_lock: threading.Lock()` | Mutex para proteger `stock_by_sku` del acceso simultáneo entre el hilo FastAPI y el hilo pika. |
| `handle_order_created(body)` | Deserializa el evento JSON, itera los ítems y resta `qty` de cada SKU. |
| `run_consumer()` | Bucle infinito con reconexión automática a RabbitMQ. Declara exchange + queue + binding, llama a `start_consuming()`. |
| `lifespan(app)` | Contexto de vida de FastAPI: arranca `run_consumer` en un `threading.Thread(daemon=True)` al iniciar. |
| `GET /` | Health check: responde `{"service": "inventory-service", "status": "ok"}` |
| `GET /internal/stock` | Devuelve el estado actual del stock: `{"items": [{"sku": "A1", "stock": 98}], "total_skus": 1}` |

#### ¿Por qué FastAPI + thread y no un script puro?

Se eligió esta arquitectura para poder **consultar el stock desde afuera** (via REST). El consumidor pika corre en un hilo daemon del mismo proceso que el servidor FastAPI, compartiendo el diccionario `stock_by_sku` (protegido con un `Lock`).

#### `Dockerfile`

```dockerfile
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
```

#### `requirements.txt`

```
pika>=1.3,<2
pydantic-settings>=2,<3
fastapi>=0.111,<1
uvicorn[standard]>=0.29,<1
```

---

### 4.9 `notification-service` (nuevo)

Servicio ligero que **simula el envío de una confirmación** (email/SMS/push) cuando se crea una orden.

#### Estructura

```
notification-service/
├── Dockerfile
├── requirements.txt
└── app/
    ├── __init__.py
    ├── config.py
    └── main.py
```

#### `app/main.py` — funciones clave

| Función | Descripción |
|---|---|
| `handle_order_created(body)` | Deserializa el evento y loguea `"confirmación enviada customer=X order_id=Y"`. |
| `run_consumer()` | Bucle infinito con reconexión a RabbitMQ. Usa la queue `notification.order-created`. |

**No expone ningún endpoint HTTP.** Es un proceso Python puro que solo consume mensajes.

#### `Dockerfile`

```dockerfile
CMD ["python", "-m", "app.main"]
```

#### `requirements.txt`

```
pika>=1.3,<2
pydantic-settings>=2,<3
```

---

### 4.10 `analytics-service` (nuevo)

Servicio que **acumula métricas en memoria** sobre las órdenes procesadas.

#### Estructura

```
analytics-service/
├── Dockerfile
├── requirements.txt
└── app/
    ├── __init__.py
    ├── config.py
    └── main.py
```

#### `app/main.py` — funciones y variables clave

| Elemento | Descripción |
|---|---|
| `metrics: dict` | Estructura en memoria: `{"orders_created_total": 0, "items_total": 0}` |
| `handle_order_created(body)` | Incrementa `orders_created_total += 1` e `items_total += sum(qty de ítems)`. Loguea el estado actual de las métricas. |
| `run_consumer()` | Bucle infinito con reconexión. Usa la queue `analytics.order-created`. |

**No expone ningún endpoint HTTP.** Las métricas solo se pueden ver en los logs del contenedor:
```
docker compose logs analytics-service
```

#### `requirements.txt`

```
pika>=1.3,<2
pydantic-settings>=2,<3
```

---

### 4.11 `Frontend/index.html`

La interfaz visual se actualizó con dos nuevos paneles:

#### Panel de flujo de eventos (`.flow-card`)

Muestra los 5 pasos del pipeline en tiempo real con colores de estado:

| Color | Estado |
|---|---|
| Gris | `idle` — paso no activado aún |
| Amarillo | `active` — en proceso |
| Verde | `done` — completado con éxito |
| Rojo | `failed` — error |

Los 5 pasos son:
1. **order-service** — recibe la orden (HTTP)
2. **Publicar evento** — publica `order.created` en RabbitMQ
3. **inventory-service** — descuenta stock
4. **notification-service** — envía confirmación
5. **analytics-service** — registra métrica

La función JS `applyFlowFromStatus(orderId, status)` actualiza el estado visual según el `status` de Redis:
- `RECEIVED` → paso 1 activo
- `PERSISTED` → pasos 1-5 en `done` (el evento ya fue publicado)
- `FAILED` → paso correspondiente en rojo

#### Panel de stock actual (`.stock-card`)

Muestra el inventario en tiempo real con tarjetas por SKU. La función JS `refreshStock()`:
1. Llama a `GET /inventory/stock` en el api-gateway
2. Renderiza una tarjeta por SKU con el stock actual

**Auto-refresh del stock:**
- Al cargar la página (`window.onload`)
- 1.2 segundos después de crear una orden (tiempo para que el evento llegue al consumer)
- Cuando el polling detecta que el estado cambió a `PERSISTED`

---

## 5. Topología RabbitMQ

```
order-service
    │
    │  publish(exchange="orders.events", routing_key="order.created")
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Exchange: orders.events  (type=topic, durable=True)        │
└─────────────────────────────────────────────────────────────┘
    │                      │                      │
    │ binding: order.created│ binding: order.created│ binding: order.created
    ▼                      ▼                      ▼
queue:                 queue:                  queue:
inventory.order-created  notification.order-created  analytics.order-created
    │                      │                      │
    ▼                      ▼                      ▼
inventory-service    notification-service    analytics-service
```

**¿Por qué `type=topic`?** Permite usar wildcards en las routing keys. Por ejemplo, en el futuro se podría tener `order.cancelled` o `order.updated` y cada consumer podría suscribirse a `order.*` o a routing keys específicas, sin cambiar el exchange.

**Durabilidad:** tanto el exchange (`durable=True`) como las queues (`durable=True`) y los mensajes (`delivery_mode=2`) sobreviven a un reinicio de RabbitMQ.

**Independencia de consumers:** cada consumer tiene su propia queue. Si se cae un consumer, los mensajes se acumulan en su queue y se procesan cuando vuelve a levantarse.

---

## 6. Nuevas variables de entorno

| Variable | Valor | Usado por |
|---|---|---|
| `INVENTORY_SERVICE_URL` | `http://inventory-service:8002` | api-gateway |
| `AMQP_URL` | `amqp://guest:guest@rabbitmq:5672/%2F` | order-service, inventory-service, notification-service, analytics-service |
| `RABBITMQ_EXCHANGE` | `orders.events` | order-service, todos los consumers |
| `ORDER_CREATED_ROUTING_KEY` | `order.created` | order-service (publisher), todos los consumers (binding) |
| `INVENTORY_QUEUE` | `inventory.order-created` | inventory-service |
| `NOTIFICATION_QUEUE` | `notification.order-created` | notification-service |
| `ANALYTICS_QUEUE` | `analytics.order-created` | analytics-service |

---

## 7. Nuevos endpoints

| Método | Ruta | Servicio | Descripción |
|---|---|---|---|
| `GET` | `/inventory/stock` | api-gateway | Proxy → inventory-service. Devuelve `{items:[{sku,stock}], total_skus}` |
| `GET` | `/internal/stock` | inventory-service | Stock actual en memoria por SKU |
| `GET` | `/` | inventory-service | Health check |

**Ejemplo de respuesta de `/inventory/stock`:**
```json
{
  "items": [
    {"sku": "A1", "stock": 98},
    {"sku": "C9", "stock": 96}
  ],
  "total_skus": 2
}
```

*(Stock inicial de cada SKU es 100. A1 bajó a 98 porque se pidieron qty=2, C9 bajó a 96 porque se pidieron qty=4).*

---

## 8. Cómo levantar el sistema

```bash
# Levantar todos los servicios desde cero
docker compose up --build

# O levantarlos en segundo plano
docker compose up --build -d

# Ver logs de todos los servicios
docker compose logs -f

# Ver logs de un servicio específico
docker compose logs -f inventory-service
docker compose logs -f analytics-service
docker compose logs -f notification-service
```

**Accesos:**
| URL | Descripción |
|---|---|
| http://localhost:3000 | Frontend visual SPA |
| http://localhost:8000/docs | API Gateway — Swagger UI |
| http://localhost:15672 | RabbitMQ Management UI (guest/guest) |
| http://localhost:8001/docs | Order Service — Swagger UI |

---

## 9. Cómo validar que todo funciona

### Paso 1 — Crear una orden
```bash
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{"customer": "Berny", "items": [{"sku": "A1", "qty": 2}, {"sku": "C9", "qty": 4}]}'
```
Respuesta esperada:
```json
{"order_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx", "status": "RECEIVED"}
```

### Paso 2 — Consultar el estado de la orden
```bash
curl http://localhost:8000/orders/<order_id>
```
Respuesta esperada (después de ~1s):
```json
{"order_id": "...", "status": "PERSISTED", "last_update": "..."}
```

### Paso 3 — Verificar el stock
```bash
curl http://localhost:8000/inventory/stock
```
Respuesta esperada:
```json
{"items": [{"sku": "A1", "stock": 98}, {"sku": "C9", "stock": 96}], "total_skus": 2}
```

### Paso 4 — Verificar los logs de los consumidores
```bash
docker compose logs notification-service
# Debe mostrar: confirmación enviada customer=Berny order_id=...

docker compose logs analytics-service
# Debe mostrar: métrica registrada order_id=... metrics={'orders_created_total': 1, 'items_total': 6}

docker compose logs inventory-service
# Debe mostrar: stock actualizado order_id=... stock={'A1': 98, 'C9': 96}
```

### Paso 5 — Ver el flujo visual en el frontend
Abrir http://localhost:3000 y crear una orden desde la interfaz. El panel de flujo mostrará los 5 pasos en verde cuando la orden sea `PERSISTED`.

---

## 10. Diagrama de arquitectura completo

```mermaid
flowchart TB
    Client["🖥️ Cliente\n(Browser / curl)"]

    subgraph docker["Docker Network"]

        subgraph gw["api-gateway :8000"]
            POST_orders["POST /orders"]
            GET_orders["GET /orders/{id}"]
            GET_stock["GET /inventory/stock"]
        end

        subgraph os["order-service :8001"]
            persist["POST /internal/orders\nupsert_order() idempotente"]
            publish["publish_order_created_event()\nasyncio.to_thread(pika)"]
        end

        Redis[("Redis :6379\norder:{id}\n• status\n• last_update")]
        Postgres[("Postgres :5432\nTabla orders")]

        subgraph mq["RabbitMQ :5672"]
            exchange["exchange: orders.events\ntype: topic\ndurable: true"]
            q1["queue:\ninventory.order-created"]
            q2["queue:\nnotification.order-created"]
            q3["queue:\nanalytics.order-created"]
        end

        subgraph inv["inventory-service :8002"]
            inv_consumer["pika consumer\n(daemon thread)"]
            inv_stock["stock_by_sku{}"]
            inv_api["GET /internal/stock"]
        end

        subgraph notif["notification-service"]
            notif_consumer["pika consumer"]
            notif_log["log: confirmación\nenviada"]
        end

        subgraph anal["analytics-service"]
            anal_consumer["pika consumer"]
            anal_metrics["metrics{}\northers_created_total\nitems_total"]
        end

        Frontend["Frontend :3000\nnginx + SPA HTML"]
    end

    Client -->|POST /orders| POST_orders
    Client -->|GET /orders/{id}| GET_orders
    Client -->|GET /inventory/stock| GET_stock
    Client <-->|puerto 3000| Frontend

    POST_orders -->|"① HSET RECEIVED"| Redis
    POST_orders -->|"② HTTP POST"| persist
    persist -->|"③ INSERT"| Postgres
    persist -->|"④ HSET PERSISTED"| Redis
    persist -->|"⑤ si created=True"| publish
    publish -->|"⑥ publish routing_key=order.created"| exchange

    exchange --> q1
    exchange --> q2
    exchange --> q3

    q1 --> inv_consumer --> inv_stock
    inv_api -->|lee con Lock| inv_stock
    GET_stock -->|proxy HTTP| inv_api

    q2 --> notif_consumer --> notif_log
    q3 --> anal_consumer --> anal_metrics

    GET_orders -->|HGETALL| Redis
```

---

## Resumen de todos los cambios

| Componente | Cambio |
|---|---|
| `docker-compose.yml` | +5 servicios: rabbitmq, inventory, notification, analytics, frontend |
| `.env` | +7 variables de RabbitMQ y URLs de nuevos servicios |
| `writer-service/app/config.py` | +3 variables: amqp_url, rabbitmq_exchange, order_created_routing_key |
| `writer-service/app/main.py` | +función `publish_order_created_event()` + llamada `asyncio.to_thread()` en POST |
| `writer-service/requirements.txt` | +`pika>=1.3,<2` |
| `api-gateway/app/config.py` | +`inventory_service_url` |
| `api-gateway/app/main.py` | +endpoint `GET /inventory/stock` (proxy) |
| `inventory-service/` | **Nuevo servicio** FastAPI + pika consumer en thread + endpoint `/internal/stock` |
| `notification-service/` | **Nuevo servicio** script pika puro, loguea confirmaciones |
| `analytics-service/` | **Nuevo servicio** script pika puro, acumula métricas en memoria |
| `Frontend/index.html` | +panel de flujo de 5 pasos con colores + panel de stock con auto-refresh |
