#!/usr/bin/env python3
"""
Console monitor for the distributed orders app.

Matches the README architecture:
- POST /orders  → 202 {order_id, status: RECEIVED}
- GET  /orders/{order_id} → {order_id, status, last_update} from Redis hash
- Writer: POST /internal/orders (idempotent, syncs Redis hash)
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


GATEWAY_BASE_URL = "http://localhost:8000"
WRITER_BASE_URL = "http://localhost:7000"


@dataclass
class HttpResult:
    status: int
    body: Any


def _http_request(method: str, url: str, payload: dict[str, Any] | None = None) -> HttpResult:
    data: bytes | None = None
    headers = {"Accept": "application/json"}

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = Request(url=url, method=method, data=data, headers=headers)

    try:
        with urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            return HttpResult(status=resp.status, body=_try_json(raw))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8") if exc.fp else ""
        return HttpResult(status=exc.code, body=_try_json(raw) if raw else {"detail": str(exc)})
    except URLError as exc:
        raise RuntimeError(f"No se pudo conectar a {url}: {exc.reason}") from exc


def _try_json(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _print_block(title: str, data: Any) -> None:
    print(f"\n=== {title} ===")
    if isinstance(data, (dict, list)):
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(data)


def check_services() -> None:
    gw = _http_request("GET", f"{GATEWAY_BASE_URL}/")
    ws = _http_request("GET", f"{WRITER_BASE_URL}/")
    _print_block(f"api-gateway / [{gw.status}]", gw.body)
    _print_block(f"writer-service / [{ws.status}]", ws.body)


def create_order(customer: str, items: list[dict]) -> HttpResult:
    payload = {"customer": customer, "items": items}
    return _http_request("POST", f"{GATEWAY_BASE_URL}/orders", payload)


def get_order_status(order_id: str) -> HttpResult:
    return _http_request("GET", f"{GATEWAY_BASE_URL}/orders/{order_id}")


def run_end_to_end_demo() -> None:
    print("\n─── Demo end-to-end (flujo README) ───")

    # Step 1: POST /orders
    print("\n① POST /orders  → api-gateway genera UUID, HSET RECEIVED, HTTP POST a writer")
    start = time.perf_counter()
    created = create_order(
        customer="Berny",
        items=[{"sku": "A1", "qty": 2}],
    )
    _print_block(f"POST /orders [{created.status}]", created.body)

    if created.status >= 400:
        print("Error al crear la orden.")
        return

    order_id = created.body.get("order_id", "")

    # Step 2: GET /orders/{order_id}
    print("\n② GET /orders/{order_id} → lee HGETALL desde Redis")
    status_res = get_order_status(order_id)
    elapsed = time.perf_counter() - start
    _print_block(f"GET /orders/{order_id} [{status_res.status}]", status_res.body)
    print(f"\nTiempo total: {elapsed:.3f} s")

    status = status_res.body.get("status", "") if isinstance(status_res.body, dict) else ""
    if status == "PERSISTED":
        print("✓ Orden persistida en PostgreSQL y estado actualizado en Redis.")
    elif status == "RECEIVED":
        print("⏳ Orden recibida (aún no confirmada como PERSISTED).")
    elif status == "FAILED":
        print("✗ Orden falló al persistir. Revisa logs: docker compose logs writer-service")
    else:
        print(f"Estado desconocido: {status}")


def test_idempotency() -> None:
    print("\n─── Test de idempotencia ───")

    created = create_order(customer="Idempotencia Test", items=[{"sku": "B2", "qty": 1}])
    _print_block(f"POST /orders [{created.status}]", created.body)
    order_id = created.body.get("order_id", "")

    time.sleep(1)

    # Send same order_id directly to writer (simulating a retry)
    print(f"\nReenviando order_id={order_id} al writer (simula retry)...")
    payload = {"order_id": order_id, "customer": "Idempotencia Test", "items": [{"sku": "B2", "qty": 1}]}
    retry_res = _http_request("POST", f"{WRITER_BASE_URL}/internal/orders", payload)
    _print_block(f"POST /internal/orders (retry) [{retry_res.status}]", retry_res.body)

    created_flag = retry_res.body.get("created", None) if isinstance(retry_res.body, dict) else None
    if created_flag is False:
        print("✓ Idempotencia confirmada: no se duplicó la orden.")
    else:
        print("⚠ La orden fue insertada de nuevo (no debería).")


def interactive_menu() -> None:
    while True:
        print("\n══════════════ Distributed Orders Monitor ══════════════")
        print("1) Health check (api-gateway + writer-service)")
        print("2) Crear orden manual")
        print("3) Consultar estado de orden (por order_id)")
        print("4) Demo end-to-end completo (recomendado)")
        print("5) Test de idempotencia")
        print("0) Salir")

        option = input("\nOpción: ").strip()

        try:
            if option == "1":
                check_services()
            elif option == "2":
                customer = input("customer: ").strip() or "Cliente CLI"
                sku = input("sku [A1]: ").strip() or "A1"
                qty_raw = input("qty [1]: ").strip() or "1"
                items = [{"sku": sku, "qty": int(qty_raw)}]

                res = create_order(customer=customer, items=items)
                _print_block(f"POST /orders [{res.status}]", res.body)

                if res.status < 400 and isinstance(res.body, dict):
                    oid = res.body.get("order_id", "")
                    print(f"\nConsultando estado inmediatamente...")
                    time.sleep(0.5)
                    status_res = get_order_status(oid)
                    _print_block(f"GET /orders/{oid} [{status_res.status}]", status_res.body)

            elif option == "3":
                oid = input("order_id (UUID): ").strip()
                if oid:
                    res = get_order_status(oid)
                    _print_block(f"GET /orders/{oid} [{res.status}]", res.body)

            elif option == "4":
                run_end_to_end_demo()
            elif option == "5":
                test_idempotency()
            elif option == "0":
                print("Saliendo...")
                return
            else:
                print("Opción no válida.")
        except ValueError:
            print("Entrada inválida.")
        except RuntimeError as exc:
            print(f"Error de conexión: {exc}")
        except Exception as exc:
            print(f"Error inesperado: {exc}")


def main() -> int:
    print("Distributed Orders Console Monitor")
    print(f"Gateway: {GATEWAY_BASE_URL}")
    print(f"Writer : {WRITER_BASE_URL}")
    print("Arquitectura: POST /orders → UUID + Redis HSET RECEIVED → HTTP POST writer → PERSISTED")
    interactive_menu()
    return 0


if __name__ == "__main__":
    sys.exit(main())
