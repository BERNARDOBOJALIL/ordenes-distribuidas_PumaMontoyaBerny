import json

import httpx
from fastapi import HTTPException, Request, Response

from ..config import settings


async def enqueue_order(redis, payload: dict) -> dict:
    """Empuja una orden a la cola Redis y retorna el estado de la cola."""
    await redis.lpush(settings.queue_name, json.dumps(payload))
    queue_len = await redis.llen(settings.queue_name)
    return {
        "message": "Orden recibida y en cola",
        "status": "en_cola",
        "posicion_en_cola": queue_len,
        "tiempo_estimado": "~10 segundos",
    }


async def forward_request(
    client: httpx.AsyncClient,
    request: Request,
    path: str,
) -> Response:
    """Reenvía cualquier petición HTTP al writer-service y devuelve su respuesta."""
    url = f"{settings.writer_service_url}{path}"
    body = await request.body()
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length", "transfer-encoding")
    }

    try:
        resp = await client.request(
            method=request.method,
            url=url,
            headers=headers,
            content=body,
            params=dict(request.query_params),
        )
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="writer-service no disponible")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timeout al conectar con writer-service")

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=dict(resp.headers),
        media_type=resp.headers.get("content-type"),
    )
