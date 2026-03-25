# Notifications Service 🔔

Microservicio de notificaciones que persiste eventos de órdenes en su propia base de datos PostgreSQL y envía confirmaciones por email usando EmailJS.

---

## 📋 Descripción General

El **Notifications Service** es un servicio interno responsable de:

1. **Consumir eventos RabbitMQ** — Escucha eventos `order.created` del broker
2. **Persistir notificaciones** — Almacena eventos de órdenes en PostgreSQL
3. **Enviar emails** — Integración con EmailJS para notificaciones por correo
4. **Recuperar historial** — Endpoints internos para consultar notificaciones por orden
5. **Caché distribuido** — Redis para sesiones y datos transitorios

**Última actualización:** Se agregó consumer RabbitMQ para escuchar eventos `order.created` en lugar de POST manuales.

---

## 🗄️ Base de Datos

### PostgreSQL Dedicada

El servicio usa su propia instancia de PostgreSQL:

```
Servidor: postgres-notifications:5432
Base de datos: notifications_db
Usuario: notifications_user
Contraseña: notifications_pass
```

### Tabla: `notifications`

```sql
CREATE TABLE notifications (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(36) NOT NULL,
    customer VARCHAR(255) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

**Campos:**
- `id` — Identificador único (auto-incremental)
- `order_id` — UUID de la orden referenciada
- `customer` — Nombre del cliente
- `event_type` — Tipo de evento (ej: `order.created`, `order.confirmed`)
- `message` — Descripción del evento
- `reason` — Motivo adicional (opcional)
- `created_at` — Timestamp de creación (UTC)

Las tablas se crean automáticamente al iniciar el servicio mediante `init_db()`.

---

## 🔌 Endpoints

Todos los endpoints son **internos** (solo accesibles dentro de la arquitectura de microservicios).

### Health Check

```
GET /
```
**Respuesta:**
```json
{
  "service": "notifications-service",
  "status": "ok",
  "version": "1.0.0"
}
```

### GET — Listar Todas las Notificaciones

```
GET /internal/notifications
```

**Response:**
```json
[
  {
    "id": 1,
    "order_id": "550e8400-e29b-41d4-a716-446655440000",
    "customer": "Berny",
    "event_type": "order.created",
    "message": "Orden creada exitosamente",
    "reason": "Recibida desde RabbitMQ",
    "created_at": "2026-03-24T10:30:00+00:00"
  },
  ...
]
```

### GET — Notificaciones por Orden

```
GET /internal/notifications/{order_id}
```

**Ejemplo:**
```
GET /internal/notifications/550e8400-e29b-41d4-a716-446655440000
```

**Response:**
```json
[
  {
    "id": 1,
    "order_id": "550e8400-e29b-41d4-a716-446655440000",
    "customer": "Berny",
    "event_type": "order.created",
    "message": "Orden creada exitosamente",
    "reason": "Recibida desde RabbitMQ",
    "created_at": "2026-03-24T10:30:00+00:00"
  }
]
```

---

## 📊 RabbitMQ Consumer

### Configuración

```
Broker: rabbitmq:5672
Universidad: amqp://guest:guest@rabbitmq:5672/
Exchange: orders.events (type: topic, durable)
Queue: notifications.queue (durable)
Routing Key: order.created
```

### Estructura del Evento

El servicio escucha eventos `order.created` publicados por **writer-service**:

```json
{
  "order_id": "550e8400-e29b-41d4-a716-446655440000",
  "customer": "Berny",
  "items": [
    { "sku": "LAPTOP-01", "qty": 2 },
    { "sku": "MOUSE-01", "qty": 1 }
  ],
  "timestamp": "2026-03-24T10:30:00+00:00"
}
```

### Flujo de Procesamiento

1. **Consume evento** — Escucha `order.created` en RabbitMQ (async)
2. **Valida JSON** — Extrae campos requeridos
3. **Persiste notificación** — INSERT en PostgreSQL
4. **Envía email** — HTTP a EmailJS (fire-and-forget)
5. **Acknowledges** — Confirma consumo al broker
6. **Maneja errores** — NACK con requeue si hay problemas

---

## 🏗️ Arquitectura de Código

```
notifications-service/
├── app/
│   ├── main.py                      # Aplicación FastAPI + lifespan + RabbitMQ consumer
│   ├── config.py                    # Variables de configuración (BD, Redis, RabbitMQ)
│   ├── db.py                        # Configuración de SQLAlchemy + init
│   ├── models.py                    # Modelos ORM (Notification)
│   ├── schemas.py                   # Esquemas Pydantic (Request/Response)
│   ├── redis_client.py              # Cliente Redis
│   ├── repositories/
│   │   └── notifications_repo.py    # Operaciones de BD (CRUD)
│   └── services/
│       ├── email_service.py         # Integración con EmailJS
│       └── rabbitmq_consumer.py     # **Consumer RabbitMQ** (NUEVO)
├── Dockerfile                        # Imagen Docker
└── requirements.txt                  # Dependencias Python
```

### Componente Nuevo: RabbitMQ Consumer

**`services/rabbitmq_consumer.py`:**
- `RabbitMQConsumer` — Clase async para conectar y consumir
- `handle_order_created_event()` — Callback que procesa eventos
- Declaración automática de exchange y queue
- Manejo de errores y requeue



### Componentes Clave

#### `models.py` — ORM
Define la tabla `Notification` usando SQLAlchemy async:

```python
class Notification(Base):
    __tablename__ = "notifications"
    id: int (PK)
    order_id: str
    customer: str
    event_type: str
    message: str
    reason: str | None
    created_at: datetime
```

#### `schemas.py` — Validación
- **`NotificationCreate`** — Payload para crear notificaciones
- **`NotificationResponse`** — Respuesta al consultar notificaciones
- **`ItemPayload`** — Estructura de items en la orden

#### `repositories/notifications_repo.py`
Encapsula las operaciones de base de datos:
- `create_notification()` — Inserta en PostgreSQL
- `get_all_notifications()` — Recupera todas
- `get_notifications_by_order()` — Filtra por order_id

#### `services/email_service.py`
Integración con EmailJS REST API:
- Construye emails HTML con detalles de la orden
- Envía de forma asíncrona (no bloquea)
- Maneja errores sin fallar la notificación

---

## ⚙️ Configuración

### Variables de Entorno (`.env`)

```env
# PostgreSQL — BD propia de notificaciones
NOTIFICATIONS_DATABASE_URL=postgresql+asyncpg://notifications_user:notifications_pass@postgres-notifications:5432/notifications_db

# Redis
REDIS_URL=redis://redis:6379/0

# RabbitMQ
AMQP_URL=amqp://guest:guest@rabbitmq:5672/
RABBITMQ_EXCHANGE=orders.events
ORDER_CREATED_ROUTING_KEY=order.created
NOTIFICATIONS_QUEUE_NAME=notifications.queue

# EmailJS
EMAILJS_SERVICE_ID=your_service_id
EMAILJS_TEMPLATE_ID=your_template_id
EMAILJS_PUBLIC_KEY=your_public_key
EMAILJS_PRIVATE_KEY=your_private_key
NOTIFICATION_TO_EMAIL=admin@example.com
```

El archivo `.env` se carga automáticamente con `pydantic_settings.BaseSettings`.

---

## 🚀 Ejecución

### Con Docker Compose

```yaml
notifications-service:
  build: ./notifications-service
  ports:
    - "8003:8000"
  environment:
    - NOTIFICATIONS_DATABASE_URL=postgresql+asyncpg://notifications_user:notifications_pass@postgres-notifications:5432/notifications_db
    - REDIS_URL=redis://redis:6379/0
    - EMAILJS_SERVICE_ID=${EMAILJS_SERVICE_ID}
    - EMAILJS_TEMPLATE_ID=${EMAILJS_TEMPLATE_ID}
    - EMAILJS_PUBLIC_KEY=${EMAILJS_PUBLIC_KEY}
    - EMAILJS_PRIVATE_KEY=${EMAILJS_PRIVATE_KEY}
  depends_on:
    - postgres-notifications
    - redis
```

### Local con Python

```bash
# Instalar dependencias
pip install -r requirements.txt

# Ejecutar servidor
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 📦 Dependencias

```
fastapi          — Framework web asincrónico
uvicorn          — Servidor ASGI
sqlalchemy       — ORM para PostgreSQL
asyncpg          — Driver async PostgreSQL
aio-pika         — Cliente RabbitMQ async (NUEVO)
redis            — Cliente Redis
httpx            — Cliente HTTP para EmailJS
pydantic         — Validación de datos
pydantic-settings— Gestión de variables de entorno
```

---

## 🔄 Flujo de Notificación

```
Writer Service (order.created event)
              ↓
RabbitMQ (exchange: orders.events, routing_key: order.created)
              ↓
Notifications Service Consumer (async, background task)
              ↓
1. Descodifica JSON del payload RabbitMQ
2. Valida campos requeridos (order_id, customer, items)
3. Persiste notificación → INSERT en PostgreSQL
4. Email async → Llamada HTTP a EmailJS (no bloquea)
5. ACK → Confirma consumo al broker
              ↓
(Si hay error durante procesamiento → NACK + Requeue automático)
```

**Garantía:** La notificación **siempre** se persiste en la BD, aunque el email falle.

---

## 🔒 Seguridad

- ✅ Endpoints son **internos** (`/internal/*`) — no expuestos públicamente
- ✅ Base de datos independiente — aislamiento de datos
- ✅ Credenciales en variables de entorno — no en código
- ✅ Async/await — manejo seguro de concurrencia
- ✅ Pool de conexiones — gestión eficiente de recursos

---

## 📊 Monitoreo

El servicio registra eventos clave:

```
[INFO] [POST /internal/notifications] order_id=... event=...
[INFO] [App] DB tables ready. Redis connected.
[INFO] ✓ Email sent for order_id=...
[WARNING] ⚠ Email failed for order_id=...: <error>
[INFO] [App] Shutdown complete.
```

---

## 🧪 Testing

### Verificar Log del Consumer

```
[2026-03-24 10:30:00] [INFO] [App] DB tables ready. Redis connected.
[2026-03-24 10:30:01] [INFO] [App] RabbitMQ consumer started.
[2026-03-24 10:30:02] [INFO] [RabbitMQ] Connected to broker
[2026-03-24 10:30:02] [INFO] [RabbitMQ] Queue 'notifications.queue' bound to exchange 'orders.events' with routing key 'order.created'
[2026-03-24 10:30:02] [INFO] [RabbitMQ] Starting consumer...
```

### Cuando Writer Service Publica un Evento

```
[2026-03-24 10:35:00] [INFO] [RabbitMQ] Received order.created event: order_id=550e8400..., customer=Berny
[2026-03-24 10:35:00] [INFO] [RabbitMQ] ✓ Notification persisted (id=1) for order_id=550e8400...
[2026-03-24 10:35:01] [INFO] [RabbitMQ] ✓ Email sent for order_id=550e8400...
```

### Consultar Notificaciones Creadas

```bash
curl http://localhost:8003/internal/notifications
```

Response:
```json
[
  {
    "id": 1,
    "order_id": "550e8400-e29b-41d4-a716-446655440000",
    "customer": "Berny",
    "event_type": "order.created",
    "message": "Orden creada exitosamente",
    "reason": "Recibida desde RabbitMQ",
    "created_at": "2026-03-24T10:35:00+00:00"
  }
]
```

---

## ❓ Preguntas Frecuentes

**¿Cómo recibe notificaciones?**
Escuchando eventos `order.created` de RabbitMQ publicados por **writer-service**. El consumer está levantado como una task async en el `lifespan` de FastAPI.

**¿Qué pasa si EmailJS falla?**
La notificación se guarda de todas formas. Solo se registra un warning. El sistema es resiliente.

**¿Qué pasa si falla la persistencia en PostgreSQL?**
El evento se hace NACK y se requeue al broker. Se reintentar automáticamente.

**¿Cómo consulto las notificaciones de una orden?**
```
GET /internal/notifications/{order_id}
```

**¿Es posible eliminar notificaciones?**
Actualmente no hay endpoint DELETE. Se guardan de forma permanente (auditoría).

**¿Integra con otros servicios?**
Sí, consume eventos del **writer-service** vía RabbitMQ. Los logs y historial está disponible para otros servicios mediante GET endpoints.

**¿Perderá mensajes si se reinicia?**
No, porque la cola es `durable=True` y se usa ACK explícito. RabbitMQ guarda mensajes hasta que se confirme el procesamiento.

## 📝 Versionado

- **Versión API:** 1.0.0
- **Última actualización:** Base de datos PostgreSQL dedicada agregada
- **Estado:** Producción

---

**Autor:** Sistema de Órdenes Distribuidas | Puma-Montoya-Berny
