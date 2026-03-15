# Distributed Orders

Sistema distribuido de ingesta de órdenes con **FastAPI**, **Postgres**, **Redis** y **RabbitMQ**.

## Arquitectura

### Diagrama de componentes

```mermaid
flowchart TB
    Client["🖥️ Cliente<br/>(curl / Postman / Front)"]

    subgraph docker["Docker Network (docker-compose)"]

        Frontend["Frontend · nginx · :3000<br/>UI visual del flujo y stock"]

        subgraph gw["api-gateway · FastAPI · :8000"]
            POST_orders["POST /orders<br/>→ 202 Accepted"]
            GET_orders["GET /orders/{id}<br/>→ 200 OK"]
            GET_stock["GET /inventory/stock<br/>→ 200 OK"]
        end

        subgraph ws["order-service · FastAPI · :8001"]
            POST_internal["POST /internal/orders<br/>→ 201 Created"]
            upsert["upsert_order()<br/>idempotente: sólo inserta<br/>si order_id no existe"]
            publish["publish_order_created_event()<br/>routing_key = order.created"]
        end

        RabbitMQ[("RabbitMQ :5672 / :15672<br/><br/>Exchange orders.events<br/>topic · durable")]

        subgraph inv["inventory-service · FastAPI + consumer · :8002"]
            INV_consume["consume order.created"]
            INV_stock["stock_by_sku{}<br/>stock inicial = 100 por SKU"]
            INV_api["GET /internal/stock"]
        end

        subgraph notif["notification-service · pika consumer"]
            NOTIF_consume["consume order.created"]
            NOTIF_send["log confirmación enviada"]
        end

        subgraph analytics["analytics-service · pika consumer"]
            ANA_consume["consume order.created"]
            ANA_metrics["metrics{}<br/>orders_created_total<br/>items_total"]
        end

        Redis[("Redis :6379<br/><br/>Hash  order:{id}<br/>• status<br/>• last_update")]

        Postgres[("Postgres :5432<br/><br/>Tabla orders<br/>• order_id — PK varchar(36)<br/>• customer — varchar(255)<br/>• items — JSON<br/>• created_at — timestamp")]
    end

    Client <-->|"http://localhost:3000"| Frontend
    Client -->|"POST /orders<br/>{customer, items:[{sku,qty}]}"| POST_orders
    Client -->|"GET /orders/{id}"| GET_orders
    Client -->|"GET /inventory/stock"| GET_stock

    POST_orders -->|"① HSET order:{id}<br/>status = RECEIVED"| Redis
    POST_orders -->|"② HTTP POST /internal/orders<br/>+ X-Request-Id<br/>timeout 1 s · 1 retry"| POST_internal
    POST_orders -.->|"Si order-service falla:<br/>HSET status = FAILED"| Redis

    POST_internal --> upsert
    upsert -->|"③ INSERT INTO orders<br/>(si no existe)"| Postgres
    upsert -->|"④ si created = true"| publish
    POST_internal -->|"⑤ HSET order:{id}<br/>status = PERSISTED"| Redis
    POST_internal -.->|"Si INSERT falla:<br/>HSET status = FAILED"| Redis
    publish -->|"⑥ publish order.created"| RabbitMQ

    RabbitMQ -->|"inventory.order-created"| INV_consume
    RabbitMQ -->|"notification.order-created"| NOTIF_consume
    RabbitMQ -->|"analytics.order-created"| ANA_consume

    INV_consume --> INV_stock
    INV_api --> INV_stock
    GET_stock -->|"proxy HTTP"| INV_api

    NOTIF_consume --> NOTIF_send
    ANA_consume --> ANA_metrics

    GET_orders -->|"⑦ HGETALL order:{id}"| Redis
```

### Diagrama de secuencia

```mermaid
sequenceDiagram
    autonumber
    actor C as Cliente
    participant GW as api-gateway :8000
    participant R as Redis :6379
    participant OS as order-service :8001
    participant PG as Postgres :5432
    participant MQ as RabbitMQ
    participant INV as inventory-service
    participant NOTIF as notification-service
    participant ANA as analytics-service

    C->>GW: POST /orders {customer, items}
    GW->>GW: genera order_id (UUID) + X-Request-Id
    GW->>R: HSET order:{id} status=RECEIVED
    GW->>OS: POST /internal/orders + X-Request-Id<br/>(timeout 1 s, max 1 retry)
    OS->>PG: SELECT … WHERE order_id = ? (idempotencia)
    alt orden no existe
        OS->>PG: INSERT INTO orders(…)
        OS->>MQ: publish order.created
        MQ-->>INV: entrega evento
        MQ-->>NOTIF: entrega evento
        MQ-->>ANA: entrega evento
        INV->>INV: descuenta stock
        NOTIF->>NOTIF: registra confirmación
        ANA->>ANA: registra métricas
        OS->>R: HSET order:{id} status=PERSISTED
        OS-->>GW: 201 Created
    else ya existe
        OS-->>GW: 201 Created (sin duplicar)
    end
    GW-->>C: 202 Accepted {order_id, status=RECEIVED}

    Note over C,ANA: Consulta posterior

    C->>GW: GET /orders/{order_id}
    GW->>R: HGETALL order:{order_id}
    GW-->>C: 200 {order_id, status, last_update}

    C->>GW: GET /inventory/stock
    GW->>INV: GET /internal/stock
    INV-->>GW: {items, total_skus}
    GW-->>C: 200 {items, total_skus}
```

### Resumen de la arquitectura

| Aspecto | Detalle |
| ------- | ------- |
| **Comunicación** | HTTP síncrona para crear/consultar órdenes + RabbitMQ para distribuir `order.created` |
| **Estado rápido** | Redis almacena hash `order:{id}` con `status` y `last_update` |
| **Persistencia** | Postgres vía SQLAlchemy async (asyncpg) |
| **Eventos** | `order-service` publica en exchange `orders.events` con routing key `order.created` |
| **Consumidores** | `inventory-service`, `notification-service` y `analytics-service` procesan el mismo evento en paralelo |
| **Trazabilidad** | `X-Request-Id` propagado desde `api-gateway` hasta `order-service` y enviado en el evento |
| **Health checks** | `pg_isready` (Postgres) · `redis-cli ping` (Redis) · `rabbitmq-diagnostics -q ping` (RabbitMQ) |
| **Dependencias** | `api-gateway` espera Redis + `order-service`; `order-service` espera Postgres + Redis + RabbitMQ |
| **Estados** | `RECEIVED` → `PERSISTED` o `FAILED` |

### Flujo

1. **POST /orders** → `api-gateway` genera `order_id`, guarda `status=RECEIVED` en Redis y envía el payload a `order-service` por HTTP.
2. **order-service** hace `upsert` en Postgres. Si la orden es nueva, publica `order.created` en RabbitMQ.
3. **inventory-service** consume el evento y descuenta stock por SKU.
4. **notification-service** consume el evento y registra la confirmación enviada.
5. **analytics-service** consume el evento y actualiza las métricas en memoria.
6. **GET /orders/{order_id}** → `api-gateway` lee el estado desde Redis.
7. **GET /inventory/stock** → `api-gateway` consulta a `inventory-service` y devuelve el stock actual.

## Estructura del proyecto

```
distributed-orders/
├── docker-compose.yml
├── .env
├── README.md
│
├── api-gateway/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py              # POST /orders, GET /orders/{id}, GET /inventory/stock
│       ├── config.py            # variables de entorno
│       ├── redis_client.py      # conexión a Redis
│       ├── schemas.py           # modelos Pydantic
│       └── services/
│           └── order_service.py # llamada HTTP al order-service + lectura de Redis
│
├── writer-service/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py              # POST /internal/orders + publish order.created
│       ├── config.py            # variables de entorno
│       ├── redis_client.py      # conexión a Redis
│       ├── db.py                # engine/session SQLAlchemy async
│       ├── models.py            # modelo ORM (Order)
│       ├── schemas.py           # modelo Pydantic (InternalOrder)
│       └── repositories/
│           └── orders_repo.py   # upsert idempotente
│
├── inventory-service/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── config.py            # RabbitMQ + queue de inventory
│       └── main.py              # consumer order.created + GET /internal/stock
│
├── notification-service/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── config.py            # RabbitMQ + queue de notification
│       └── main.py              # consumer order.created + log de confirmación
│
├── analytics-service/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── config.py            # RabbitMQ + queue de analytics
│       └── main.py              # consumer order.created + métricas
│
└── Frontend/
    ├── Dockerfile
    └── index.html               # UI visual del flujo, historial y stock
```

## Servicios

| Servicio | Puerto | Descripción |
| -------- | ------ | ----------- |
| **frontend** | 3000 | Interfaz visual para crear órdenes, ver flujo y stock |
| **api-gateway** | 8000 | API pública. Crea órdenes, consulta estado, lista órdenes y expone stock |
| **order-service** | 8001 | Servicio interno. Persiste en Postgres y publica `order.created` |
| **inventory-service** | 8002 interno | Consume eventos y descuenta stock |
| **notification-service** | interno | Consume eventos y registra confirmaciones |
| **analytics-service** | interno | Consume eventos y registra métricas |
| **rabbitmq** | 5672 / 15672 | Broker AMQP + UI de administración |
| **postgres** | 5432 | Base de datos relacional |
| **redis** | 6379 | Caché de estado de órdenes |

## Endpoints

### API Gateway

| Método | Ruta                 | Descripción                                                                    |
| ------ | -------------------- | ------------------------------------------------------------------------------ |
| `POST` | `/orders`            | Crea una orden. Body: `{ "customer": "...", "items": [{"sku":"A1","qty":2}] }` |
| `GET`  | `/orders/{order_id}` | Consulta el estado de una orden                                                |
| `GET`  | `/orders`            | Lista todas las órdenes persistidas desde Postgres vía `order-service`         |
| `GET`  | `/inventory/stock`   | Consulta el stock actual vía `inventory-service`                               |

### Order Service (interno)

| Método | Ruta               | Descripción                                     |
| ------ | ------------------ | ----------------------------------------------- |
| `POST` | `/internal/orders` | Persiste la orden en Postgres, actualiza Redis y publica `order.created` |
| `GET`  | `/internal/orders` | Lista todas las órdenes guardadas en Postgres   |

### Inventory Service (interno)

| Método | Ruta              | Descripción |
| ------ | ----------------- | ----------- |
| `GET`  | `/`               | Health check del servicio |
| `GET`  | `/internal/stock` | Devuelve el stock actual en memoria |

## Características distribuidas

- **Correlación**: header `X-Request-Id` propagado desde `api-gateway` hacia `order-service` y enviado dentro del evento.
- **Timeout + retry**: `api-gateway` usa timeout de 1 s y 1 reintento al llamar a `order-service`.
- **Idempotencia**: `order-service` verifica si el `order_id` ya existe antes de insertar y solo publica el evento cuando la orden es nueva.
- **Mensajería**: RabbitMQ distribuye `order.created` a tres colas distintas, una por consumidor.
- **Stock visible**: `inventory-service` expone el stock actual por HTTP y el `api-gateway` lo publica hacia el cliente.
- **Estados en Redis**: `RECEIVED` → `PERSISTED` | `FAILED`.

## Cómo ejecutar

```bash
# Levantar todos los servicios
docker compose up --build

# Crear una orden
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
    -d '{"customer": "Berny", "items": [{"sku": "A1", "qty": 2}, {"sku": "C9", "qty": 4}]}'

# Consultar estado (usar el order_id devuelto)
curl http://localhost:8000/orders/<order_id>

# Consultar stock actual
curl http://localhost:8000/inventory/stock
```

## Variables de entorno

Definidas en `.env` y compartidas vía `docker-compose.yml`:

| Variable                 | Valor por defecto                                                      |
| ------------------------ | ---------------------------------------------------------------------- |
| `POSTGRES_USER`          | `orders_user`                                                          |
| `POSTGRES_PASSWORD`      | `orders_pass`                                                          |
| `POSTGRES_DB`            | `orders_db`                                                            |
| `DATABASE_URL`           | `postgresql+asyncpg://orders_user:orders_pass@postgres:5432/orders_db` |
| `REDIS_URL`              | `redis://redis:6379/0`                                                 |
| `WRITER_SERVICE_URL`     | `http://order-service:8001`                                            |
| `INVENTORY_SERVICE_URL`  | `http://inventory-service:8002`                                        |
| `AMQP_URL`               | `amqp://guest:guest@rabbitmq:5672/%2F`                                 |
| `RABBITMQ_EXCHANGE`      | `orders.events`                                                        |
| `ORDER_CREATED_ROUTING_KEY` | `order.created`                                                    |
| `INVENTORY_QUEUE`        | `inventory.order-created`                                              |
| `NOTIFICATION_QUEUE`     | `notification.order-created`                                           |
| `ANALYTICS_QUEUE`        | `analytics.order-created`                                              |
| `WRITER_TIMEOUT_SECONDS` | `1.0`                                                                  |
| `WRITER_MAX_RETRIES`     | `1`                                                                    |
