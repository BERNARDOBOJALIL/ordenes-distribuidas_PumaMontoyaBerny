# Guia Paso a Paso - Distributed Orders

Esta guia explica el proyecto de forma simple, desde cero.

## 1. Que hace este sistema

Este sistema recibe ordenes y las guarda en base de datos.

Componentes:
- `api-gateway` (puerto `8000`): entrada publica.
- `writer-service` (puerto `8001`): guarda en PostgreSQL.
- `redis` (puerto `6379`): guarda estado rapido de cada orden.
- `postgres` (puerto `5432`): guarda las ordenes definitivas.
- `frontend` (puerto `3000`): interfaz web.

Flujo simple:
1. El cliente manda `POST /orders` al `api-gateway`.
2. El gateway genera `order_id` (UUID).
3. El gateway guarda en Redis: `order:{id}` con `status=RECEIVED`.
4. El gateway manda la orden al `writer-service` (`POST /internal/orders`).
5. El writer guarda en PostgreSQL (idempotente: si ya existe, no duplica).
6. El writer actualiza Redis a `PERSISTED` o `FAILED`.
7. El cliente consulta `GET /orders/{order_id}` y lee estado desde Redis.

## 2. Requisitos

Necesitas:
- Docker Desktop (con Docker Compose)
- PowerShell (Windows)

## 3. Archivos importantes

- `docker-compose.yml`
- `.env`
- `api-gateway/app/main.py`
- `api-gateway/app/services/order_service.py`
- `writer-service/app/main.py`
- `writer-service/app/repositories/orders_repo.py`
- `console_monitor.py`
- `Frontend/index.html`

## 4. Configuracion de entorno

El archivo `.env` ya trae valores por defecto. Debe verse similar a esto:

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

## 5. Levantar todo (build limpio)

Desde la raiz del proyecto:

```powershell
cd "c:\Users\Windows\Desktop\hola\ordenes-distribuidas_PumaMontoyaBerny"

# Limpia contenedores, red y volumen de Postgres
docker compose down -v --remove-orphans

# Construye y levanta todo en segundo plano
docker compose up --build -d

# Verifica estado
docker compose ps
```

Debes ver arriba:
- `postgres` (healthy)
- `redis` (healthy)
- `writer-service` (Up)
- `api-gateway` (Up)
- `frontend` (Up)

## 6. Probar rapidamente (API)

### 6.1 Crear orden

```powershell
$body = '{"customer":"Berny","items":[{"sku":"A1","qty":2}]}'
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/orders" -ContentType "application/json" -Body $body
```

Respuesta esperada (ejemplo):

```json
{
  "order_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "RECEIVED"
}
```

### 6.2 Consultar estado

```powershell
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/orders/<order_id>"
```

Respuesta esperada (ejemplo):

```json
{
  "order_id": "...",
  "status": "PERSISTED",
  "last_update": "2026-03-08T17:05:34.208663+00:00"
}
```

## 7. Probar desde el frontend

Abre en navegador:
- `http://localhost:3000`

Pasos:
1. Llena `customer`.
2. Agrega item (`sku`, `qty`).
3. Click en crear orden.
4. Copia el `order_id`.
5. Consulta estado.

Nota: la hora en pantalla se convierte a zona Mexico (`America/Mexico_City`, GMT-6).

## 8. Usar el monitor de consola

```powershell
python console_monitor.py
```

En el menu puedes:
- Revisar health.
- Crear orden manual.
- Consultar estado por `order_id`.
- Ejecutar demo de punta a punta.
- Probar idempotencia.

## 9. Endpoints principales

### API Gateway
- `POST /orders`
- `GET /orders/{order_id}`
- `GET /orders` (lista desde PostgreSQL via writer)

### Writer Service (interno)
- `POST /internal/orders`
- `GET /internal/orders`

## 10. Como leer logs

```powershell
docker compose logs -f api-gateway writer-service postgres redis frontend
```

Que buscar:
- En `api-gateway`: intentos y `X-Request-Id`.
- En `writer-service`: `Created` o `Already existed`.
- En `postgres`: errores de conexion o esquema.

## 11. Problemas comunes

### 11.1 Error de base de datos
Usa build limpio:

```powershell
docker compose down -v --remove-orphans
docker compose up --build -d
```

### 11.2 `status=FAILED`
Revisa logs del writer:

```powershell
docker compose logs --tail 100 writer-service
```

### 11.3 Frontend no carga
Verifica contenedor:

```powershell
docker compose ps
```

Si `frontend` no aparece, revisa el nombre de carpeta (`Frontend` vs `frontend`) y reconstruye.

## 12. Apagar todo

```powershell
docker compose down
```

Si quieres limpiar tambien la base:

```powershell
docker compose down -v
```

---

Si quieres, te puedo hacer una version aun mas corta tipo "cheat sheet" (solo comandos utiles).