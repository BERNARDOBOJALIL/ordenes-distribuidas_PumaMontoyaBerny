#!/usr/bin/env bash
set -euo pipefail

# Test 05: valida que notification-service procese el evento de orden revisando logs del contenedor.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/helpers.sh"
load_state

[ -n "${ORDER_ID:-}" ] || fail "ORDER_ID missing in state"

log "05: verify notification consumer processed order_id=$ORDER_ID"
FOUND_NOTIFICATION_LOG=""
for _ in $(seq 1 40); do
  # Se busca trazas de procesamiento del order_id en los logs del servicio.
  LOGS="$(docker compose logs --no-color notification-service 2>/dev/null || true)"

  if printf '%s' "$LOGS" | grep -F "order_id=$ORDER_ID" >/dev/null 2>&1; then
    FOUND_NOTIFICATION_LOG="yes"
    break
  fi

  if printf '%s' "$LOGS" | grep -F "$ORDER_ID" >/dev/null 2>&1; then
    FOUND_NOTIFICATION_LOG="yes"
    break
  fi

  sleep 2
done

[ "$FOUND_NOTIFICATION_LOG" = "yes" ] || fail "No notification logs found for order_id=$ORDER_ID"
log "05: notification test passed"
