# Despliegue en Railway (Guia para otra IA)

Este documento describe exactamente como quiero desplegar este proyecto en Railway con plan gratuito, dividido entre dos cuentas.

## Objetivo de despliegue

- Usar 2 cuentas de Railway.
- Dividir solo estos microservicios de aplicacion:
  - `api-gateway`
  - `writer-service`
  - `inventory-service`
  - `notifications-service`
- La infraestructura (Postgres, Redis, RabbitMQ) estara en la Cuenta A.
- La Cuenta B debe conectarse a infraestructura de la Cuenta A usando URLs publicas y credenciales.

## Reparto entre cuentas

### Cuenta A

- `api-gateway`
- `writer-service`
- `Postgres` (servicio gestionado Railway)
- `Redis` (servicio gestionado Railway)
- `RabbitMQ` (plugin/servicio gestionado o equivalente)

### Cuenta B

- `inventory-service`
- `notifications-service`

## Regla de conectividad

- Misma cuenta/proyecto de Railway: preferir red privada + `${{...}}`.
- Cuenta distinta: usar endpoint publico (dominio `*.up.railway.app`) y credenciales seguras en variables.

## Root Directory por servicio

Configurar cada servicio para construir su carpeta, no la raiz del repo:

- `api-gateway` -> `api-gateway/`
- `writer-service` -> `writer-service/`
- `inventory-service` -> `inventory-service/`
- `notifications-service` -> `notifications-service/`

Builder recomendado: Dockerfile (cada carpeta ya tiene su Dockerfile).

## Variables de entorno requeridas

## 1) api-gateway (Cuenta A)

Variables exactas que debo cargar en Railway para `api-gateway`:

```env
WRITER_SERVICE_URL=http://${{writer-service.RAILWAY_PRIVATE_DOMAIN}}:8001
INVENTORY_SERVICE_URL=https://inventory-service-xxxx.up.railway.app
NOTIFICATIONS_SERVICE_URL=https://notifications-service-xxxx.up.railway.app
REDIS_URL=${{Redis.REDIS_URL}}
WRITER_TIMEOUT_SECONDS=8
WRITER_MAX_RETRIES=2
```

Notas:
- `INVENTORY_SERVICE_URL` y `NOTIFICATIONS_SERVICE_URL` son publicas porque estan en Cuenta B.
- `REDIS_URL` se toma de Redis de Cuenta A por referencia `${{...}}`.

## 2) writer-service (Cuenta A)

Variables exactas para `writer-service`:

```env
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
AMQP_URL=${{RabbitMQ.AMQP_URL}}
```

Opcionales utiles:

```env
RABBITMQ_EXCHANGE=orders.events
ORDER_CREATED_ROUTING_KEY=order.created
```

## 3) inventory-service (Cuenta B)

Variables exactas para `inventory-service`:

```env
INVENTORY_DATABASE_URL=postgresql+asyncpg://<user>:<pass>@<host-publico-cuenta-a>:<port>/<db>
REDIS_URL=redis://<user>:<pass>@<host-publico-cuenta-a>:<port>/0
```

Si Postgres y Redis de Cuenta A exponen URL publica lista para usar, pegar esa URL directa.

## 4) notifications-service (Cuenta B)

Variables exactas para `notifications-service`:

```env
NOTIFICATIONS_DATABASE_URL=postgresql+asyncpg://<user>:<pass>@<host-publico-cuenta-a>:<port>/<db>
REDIS_URL=redis://<user>:<pass>@<host-publico-cuenta-a>:<port>/0
AMQP_URL=amqps://<user>:<pass>@<host-publico-cuenta-a>:<port>/<vhost>

EMAILJS_SERVICE_ID=<valor>
EMAILJS_TEMPLATE_ID=<valor>
EMAILJS_PUBLIC_KEY=<valor>
EMAILJS_PRIVATE_KEY=<valor>
NOTIFICATION_TO_EMAIL=<correo-destino>
```

## Convencion de nombres para `${{...}}`

Importante:
- El identificador antes del punto debe coincidir con el nombre exacto del servicio en Railway.
- Ejemplo: si el servicio se llama `redis-prod`, entonces usar `${{redis-prod.REDIS_URL}}`, no `${{Redis.REDIS_URL}}`.

## Orden de despliegue esperado

1. En Cuenta A: crear `Postgres`, `Redis`, `RabbitMQ`.
2. En Cuenta A: desplegar `writer-service` y validar health.
3. En Cuenta B: desplegar `inventory-service` y `notifications-service` usando endpoints publicos de infraestructura de Cuenta A.
4. En Cuenta A: desplegar `api-gateway` apuntando a URLs publicas de Cuenta B.
5. Probar flujo completo de orden.

## Pruebas minimas post-despliegue

1. `GET /` en cada microservicio responde `200`.
2. `POST /orders` en `api-gateway` retorna `202` con `order_id`.
3. `GET /orders/{order_id}` refleja estado (`RECEIVED`, luego `PERSISTED` o `FAILED`).
4. `GET /notifications/{order_id}` muestra notificaciones si aplica.

## Errores comunes y como evitarlos

- Error de Railpack en raiz del repo:
  - Causa: intentar desplegar monorepo desde raiz.
  - Solucion: configurar Root Directory por servicio.

- Servicios entre cuentas no se encuentran:
  - Causa: usar hostname privado entre cuentas.
  - Solucion: usar URL publica `https://...up.railway.app`.

- Variables `${{...}}` no resuelven:
  - Causa: nombre de servicio incorrecto.
  - Solucion: copiar nombre exacto del servicio Railway.

## Preferencias explicitas para futuras IAs

- Mantener esta estrategia de 2 cuentas.
- No intentar desplegar toda la infraestructura en Cuenta B.
- Conservar `api-gateway` + `writer-service` en Cuenta A.
- Conservar `inventory-service` + `notifications-service` en Cuenta B.
- Usar `${{...}}` siempre que el recurso este en la misma cuenta/proyecto.
- Usar endpoints publicos solo para conexiones cross-account.
