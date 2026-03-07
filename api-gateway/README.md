# API Gateway – Órdenes Distribuidas

Punto de entrada único del sistema. Corre en `http://localhost:8000`.

---

## Arquitectura

```
Cliente ──► API Gateway :8000 ──► Redis (cola: orders_queue)
                                       └── writer-service :8001 ──► PostgreSQL
```

- **POST /orders** → el gateway empuja la orden a Redis; el writer-service la consume y guarda en PostgreSQL (~10 s).
- **GET / PUT / DELETE /orders** → el gateway reenvía la petición directamente al writer-service.

---

## Endpoints

| Método   | Ruta                | Status | Descripción                              |
|----------|---------------------|--------|------------------------------------------|
| GET      | `/`                 | 200    | Estado del gateway                       |
| GET      | `/health`           | 200/207| Health-check de Redis y writer-service   |
| GET      | `/queue/status`     | 200    | Órdenes pendientes en la cola Redis      |
| **POST** | `/orders`           | **202**| Crea orden → encola en Redis             |
| GET      | `/orders`           | 200    | Lista órdenes (desde PostgreSQL)         |
| GET      | `/orders/{id}`      | 200    | Obtiene orden por ID                     |
| PUT      | `/orders/{id}`      | 200    | Actualiza orden                          |
| DELETE   | `/orders/{id}`      | 204    | Elimina orden                            |

Docs interactivas: `http://localhost:8000/docs`

---

## Schemas

### `OrderCreate` — body de `POST /orders` (todos requeridos excepto `estado`)

```json
{
  "cliente":  "Juan Pérez",
  "producto": "Laptop",
  "cantidad": 2,
  "precio":   999.99,
  "estado":   "pendiente"
}
```

### `OrderUpdate` — body de `PUT /orders/{id}` (todos opcionales)

```json
{
  "cliente":  "Ana López",
  "producto": "Monitor",
  "cantidad": 1,
  "precio":   350.00,
  "estado":   "completado"
}
```

**Estados válidos**: `pendiente` | `en_proceso` | `completado` | `cancelado`

### Respuesta `POST /orders` (202 Accepted)

```json
{
  "message":          "Orden recibida y en cola",
  "status":           "en_cola",
  "posicion_en_cola": 3,
  "tiempo_estimado":  "~10 segundos"
}
```

---

## Lo que deben implementar (writer-service `:8001`)

El writer-service necesita exponer:

| Método | Ruta            | Descripción                        |
|--------|-----------------|------------------------------------|
| GET    | `/`             | `{"status": "ok"}` (para health)   |
| GET    | `/orders`       | Lista todas las órdenes de la BD   |
| GET    | `/orders/{id}`  | Retorna orden por ID               |
| PUT    | `/orders/{id}`  | Actualiza campos de la orden       |
| DELETE | `/orders/{id}`  | Elimina la orden                   |

Y debe consumir la cola `orders_queue` de Redis (con `BRPOP` o similar) para persistir órdenes en PostgreSQL.

---

## Variables de entorno (`.env`)

```env
WRITER_SERVICE_URL=http://writer-service:8001
REDIS_URL=redis://redis:6379
```

---

## Levantar

```bash
docker compose up --build
```
