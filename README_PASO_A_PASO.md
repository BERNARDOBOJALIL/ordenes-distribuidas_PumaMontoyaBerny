# Guia Paso a Paso - Distributed Orders

Esta guia explica el proyecto de forma sencilla: que hace cada archivo, como funciona el sistema y como usarlo desde cero.

---

## 1. Que hace este sistema

Recibe ordenes de compra y las guarda de forma segura en base de datos.

Tiene 5 piezas que trabajan juntas:

| Pieza | Puerto | Que hace |
|---|---|---|
| `api-gateway` | 8000 | Recibe peticiones del cliente. Es la "puerta de entrada". |
| `writer-service` | 8001 | Guarda las ordenes en la base de datos. Solo lo llama el gateway. |
| `redis` | 6379 | Guarda el estado rapido de cada orden (RECEIVED, PERSISTED, FAILED). |
| `postgres` | 5432 | Base de datos principal donde quedan guardadas las ordenes para siempre. |
| `frontend` | 3000 | Pagina web para usar el sistema desde el navegador. |

---

## 2. Como fluye una orden (paso a paso)

```
Cliente
  │
  │  POST /orders  {customer, items}
  ▼
api-gateway
  │  1. Genera order_id (UUID unico)
  │  2. Genera X-Request-Id (para rastrear la peticion)
  │  3. Guarda en Redis:  order:{id} → status = RECEIVED
  │  4. Llama al writer-service (timeout 1s, 1 reintento)
  ▼
writer-service  POST /internal/orders
  │  5. Verifica si el order_id ya existe en Postgres (idempotencia)
  │  6. Si no existe → INSERT en tabla orders
  │  7. Actualiza Redis:  order:{id} → status = PERSISTED
  │     Si algo falla  → status = FAILED
  ▼
Postgres  (orden guardada definitivamente)

Cliente
  │
  │  GET /orders/{order_id}
  ▼
api-gateway
  │  Lee HGETALL order:{id} desde Redis
  ▼
Respuesta: { order_id, status, last_update }
```

**Idempotencia**: si el gateway llama dos veces al writer con el mismo `order_id`, la orden NO se duplica en Postgres.

---

## 3. Estructura de carpetas

```
ordenes-distribuidas/
├── docker-compose.yml          # orquesta todos los servicios
├── .env                        # variables de entorno (passwords, URLs)
├── console_monitor.py          # programa de consola para probar el sistema
│
├── api-gateway/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py             # define los endpoints publicos
│       ├── config.py           # lee variables de entorno
│       ├── schemas.py          # define la forma de los datos (modelos)
│       ├── redis_client.py     # crea la conexion a Redis
│       └── services/
│           └── order_service.py  # logica de negocio principal
│
├── writer-service/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py             # define los endpoints internos
│       ├── config.py           # lee variables de entorno
│       ├── schemas.py          # define la forma de los datos
│       ├── redis_client.py     # crea la conexion a Redis
│       ├── db.py               # conexion y sesion de PostgreSQL
│       ├── models.py           # tabla orders en SQLAlchemy
│       └── repositories/
│           └── orders_repo.py  # insert idempotente y consultas
│
└── Frontend/
    ├── Dockerfile
    └── index.html              # interfaz web (una sola pagina)
```

---

## 4. Que hay en cada archivo y para que sirve

### 4.1 `docker-compose.yml`

Orquesta (levanta y conecta) todos los servicios con un solo comando.

Puntos clave:
- `postgres` espera estar `healthy` antes de que `writer-service` arranque.
- `redis` tambien espera estar `healthy`.
- `api-gateway` espera que `writer-service` haya iniciado.
- El healthcheck de Postgres usa `-d ${POSTGRES_DB}` para verificar la base correcta.

---

### 4.2 `.env`

Contiene las contrasenas y URLs que usan los servicios.

```env
POSTGRES_USER=orders_user
POSTGRES_PASSWORD=orders_pass
POSTGRES_DB=orders_db
DATABASE_URL=postgresql+asyncpg://orders_user:orders_pass@postgres:5432/orders_db

REDIS_URL=redis://redis:6379/0
WRITER_SERVICE_URL=http://writer-service:8001
WRITER_TIMEOUT_SECONDS=1.0
WRITER_MAX_RETRIES=1
```

---

### 4.3 `api-gateway/app/config.py`

Lee las variables del `.env` y las expone como objeto `settings`.

Variables que maneja:
- `writer_service_url`: donde esta el writer-service.
- `redis_url`: donde esta Redis.
- `writer_timeout_seconds`: cuanto tiempo esperar respuesta del writer (1 segundo).
- `writer_max_retries`: cuantos reintentos si el writer no responde (1).

---

### 4.4 `api-gateway/app/schemas.py`

Define la "forma" de los datos que entran y salen del gateway.

| Modelo | Uso | Campos |
|---|---|---|
| `ItemPayload` | Un articulo de la orden | `sku` (codigo), `qty` (cantidad > 0) |
| `OrderCreate` | Body del `POST /orders` | `customer`, `items` (lista de ItemPayload) |
| `OrderAccepted` | Respuesta del `POST /orders` 202 | `order_id`, `status` |
| `OrderStatus` | Respuesta del `GET /orders/{id}` | `order_id`, `status`, `last_update` |

---

### 4.5 `api-gateway/app/redis_client.py`

Crea una conexion asincrona a Redis usando la URL de `config.py`.

Funcion: `get_redis()` — retorna un cliente Redis listo para usar.

---

### 4.6 `api-gateway/app/main.py`

Servidor FastAPI del gateway. Define los endpoints publicos.

Funciones clave:

| Funcion | Endpoint | Que hace |
|---|---|---|
| `lifespan` | — | Al arrancar, crea cliente HTTP y conexion Redis. Al apagar, los cierra. |
| `crear_orden` | `POST /orders` | Genera UUID, llama a `send_to_writer`, devuelve 202. |
| `obtener_orden` | `GET /orders/{order_id}` | Lee el hash de Redis y devuelve estado. |
| `listar_ordenes` | `GET /orders` | Proxy a `GET /internal/orders` del writer (lista desde Postgres). |

---

### 4.7 `api-gateway/app/services/order_service.py`

Contiene la logica principal del gateway. Es el cerebro del flujo.

Funciones:

**`send_to_writer(http_client, redis, order_id, customer, items)`**
1. Guarda en Redis: `order:{id}` → `status=RECEIVED`.
2. Genera `X-Request-Id` para rastrear la peticion.
3. Hace `POST /internal/orders` al writer con timeout de 1s.
4. Reintenta 1 vez si falla.
5. Si todos los intentos fallan → guarda `status=FAILED` en Redis.

**`get_order_status(redis, order_id)`**
- Hace `HGETALL order:{id}` en Redis.
- Retorna el diccionario con `status` y `last_update`, o `None` si no existe.

---

### 4.8 `writer-service/app/config.py`

Lee variables del `.env` para el writer.

Variables que maneja:
- `database_url`: URL de conexion a Postgres con driver asyncpg.
- `redis_url`: donde esta Redis.

---

### 4.9 `writer-service/app/schemas.py`

Define los datos que espera recibir el writer del gateway.

| Modelo | Uso | Campos |
|---|---|---|
| `ItemPayload` | Un articulo | `sku`, `qty` |
| `InternalOrder` | Body de `POST /internal/orders` | `order_id`, `customer`, `items` |

---

### 4.10 `writer-service/app/redis_client.py`

Crea una conexion a Redis.

Funcion: `get_redis_client()` — retorna cliente Redis asincrono.

---

### 4.11 `writer-service/app/db.py`

Configura la conexion a PostgreSQL.

Objetos y funciones:

| Nombre | Que hace |
|---|---|
| `engine` | Motor de conexion asincrona a Postgres (con `pool_pre_ping` para reconectar). |
| `AsyncSessionLocal` | Fabrica de sesiones de base de datos. |
| `init_db()` | Crea la tabla `orders` si no existe. Se llama al arrancar. |
| `get_session()` | Dependencia de FastAPI: entrega una sesion y la cierra al terminar. |

---

### 4.12 `writer-service/app/models.py`

Define la tabla `orders` en PostgreSQL usando SQLAlchemy.

Columnas de la tabla:

| Columna | Tipo | Descripcion |
|---|---|---|
| `order_id` | VARCHAR(36) PK | UUID de la orden. Clave primaria. |
| `customer` | VARCHAR(255) | Nombre del cliente. |
| `items` | TEXT | Lista de articulos en formato JSON. |
| `created_at` | DATETIME | Fecha y hora de creacion (UTC). |

---

### 4.13 `writer-service/app/repositories/orders_repo.py`

Capa de acceso a datos. Todas las operaciones con Postgres pasan por aqui.

Funciones:

**`upsert_order(session, order_id, customer, items)`**
- Verifica si ya existe una fila con ese `order_id`.
- Si ya existe → la retorna sin insertar (idempotencia).
- Si no existe → crea la fila y la retorna.
- Devuelve `(order, created)`: `created=True` si fue nueva, `False` si ya existia.

**`get_order(session, order_id)`**
- Busca una orden por su `order_id`.
- Retorna el objeto `Order` o `None` si no existe.

**`get_all_orders(session)`**
- Retorna todas las ordenes guardadas.

---

### 4.14 `writer-service/app/main.py`

Servidor FastAPI del writer. Solo acepta llamadas del gateway (no es publico).

Funciones clave:

| Funcion | Endpoint | Que hace |
|---|---|---|
| `lifespan` | — | Al arrancar: llama `init_db()` y conecta Redis. Al apagar: cierra Redis. |
| `root` | `GET /` | Health check: responde `{"status": "ok"}`. |
| `persist_order` | `POST /internal/orders` | Guarda la orden en Postgres. Actualiza Redis a PERSISTED o FAILED. |
| `list_orders` | `GET /internal/orders` | Lista todas las ordenes desde Postgres. |

Flujo dentro de `persist_order`:
1. Recibe `InternalOrder` + encabezado `X-Request-Id`.
2. Llama a `upsert_order` (idempotente).
3. Si ok → `HSET order:{id} status=PERSISTED`.
4. Si error → `HSET order:{id} status=FAILED`.

---

### 4.15 `Frontend/index.html`

Pagina web de una sola archivo. No necesita compilarse.

Funciones JavaScript principales:

| Funcion | Que hace |
|---|---|
| `checkHealth()` | Llama a `GET /` del gateway cada 10s. Muestra el pastillo verde/rojo. |
| `createOrder()` | Toma los datos del formulario, llama a `POST /orders`, muestra respuesta. |
| `queryOrder()` | Llama a `GET /orders/{id}` y muestra estado. |
| `togglePoll()` | Activa/desactiva consulta automatica cada 2 segundos. |
| `loadHistory()` | Al cargar la pagina, obtiene ordenes guardadas de Postgres via `GET /orders`. |
| `renderLog()` | Dibuja la lista de ordenes en pantalla. |
| `formatMxTime(value)` | Convierte cualquier timestamp UTC a zona Mexico (GMT-6) para mostrarlo. |
| `showToast(msg, type)` | Muestra notificacion temporal (verde=exito, rojo=error). |

---

### 4.16 `console_monitor.py`

Programa Python de consola para probar el sistema sin abrir el navegador.

Funciones:

| Funcion | Que hace |
|---|---|
| `check_services()` | Llama a `GET /` del gateway y writer. Muestra si estan arriba. |
| `create_order(customer, items)` | Envia `POST /orders` al gateway. |
| `get_order_status(order_id)` | Consulta estado de una orden. |
| `run_end_to_end_demo()` | Crea orden real, espera respuesta y muestra el estado final. |
| `test_idempotency()` | Crea orden y la reintenta. Verifica que no se duplique en Postgres. |

---

## 5. Requisitos

- Docker Desktop (con Docker Compose incluido)
- PowerShell (Windows)
- Python 3.11+ (solo para `console_monitor.py`)

---

## 6. Configurar y levantar

### Primera vez (o cuando cambias codigo):

```powershell
cd "c:\Users\Windows\Desktop\hola\ordenes-distribuidas_PumaMontoyaBerny"

docker compose down -v --remove-orphans
docker compose up --build -d
docker compose ps
```

Debes ver todos los servicios en `Up` o `healthy`:

```
api-gateway      Up   0.0.0.0:8000->8000/tcp
writer-service   Up   0.0.0.0:8001->8001/tcp
postgres         Up (healthy)   0.0.0.0:5432->5432/tcp
redis            Up (healthy)   0.0.0.0:6379->6379/tcp
frontend         Up   0.0.0.0:3000->80/tcp
```

---

## 7. Probar el sistema

### Desde PowerShell

Crear orden:
```powershell
$body = '{"customer":"Berny","items":[{"sku":"A1","qty":2}]}'
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/orders" -ContentType "application/json" -Body $body
```

Consultar estado (reemplaza el UUID):
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/orders/<order_id>"
```

### Desde el navegador

Abre `http://localhost:3000`

### Desde el monitor de consola

```powershell
python console_monitor.py
```

---

## 8. Endpoints del sistema

### API Gateway (puerto 8000, publico)

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/orders` | Crea una orden. Devuelve `{order_id, status}`. |
| `GET` | `/orders/{order_id}` | Consulta estado desde Redis. |
| `GET` | `/orders` | Lista todas las ordenes desde Postgres. |

### Writer Service (puerto 8001, interno)

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/internal/orders` | Guarda orden en Postgres. Actualiza Redis. |
| `GET` | `/internal/orders` | Lista todas las ordenes. |
| `GET` | `/` | Health check. |

---

## 9. Ver logs en tiempo real

```powershell
docker compose logs -f api-gateway writer-service
```

Que buscar en los logs:
- `[send_to_writer] attempt 1/2` — el gateway intentando llegar al writer.
- `X-Request-Id=...` — el ID de rastreo propagado entre ambos servicios.
- `✓ Created order_id=...` — orden guardada con exito en Postgres.
- `Already existed order_id=...` — orden duplicada bloqueada (idempotencia).
- `✗ FAILED order_id=...` — algo salio mal al guardar.

---

## 10. Problemas comunes

### `status=FAILED` al crear orden

```powershell
docker compose logs --tail 100 writer-service
```

Si ves errores de Postgres, haz rebuild limpio:
```powershell
docker compose down -v --remove-orphans
docker compose up --build -d
```

### Frontend muestra error de conexion

Verifica que el gateway este corriendo:
```powershell
docker compose ps
```

Si `api-gateway` no esta `Up`, revisa sus logs:
```powershell
docker compose logs api-gateway
```

### Cambios en el codigo no se reflejan

Siempre reconstruye con `--build`:
```powershell
docker compose up --build -d
```

---

## 11. Apagar

```powershell
# Solo apaga, conserva datos en Postgres
docker compose down

# Apaga y borra todos los datos
docker compose down -v
```