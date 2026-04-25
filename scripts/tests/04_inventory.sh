#!/usr/bin/env bash
set -euo pipefail

# Test 04: valida inventario y confirma que el evento de orden impacta el stock.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/helpers.sh"
load_state

[ -n "${ACCESS_TOKEN:-}" ] || fail "ACCESS_TOKEN missing in state"
[ -n "${ORDER_SKU:-}" ] || fail "ORDER_SKU missing in state"

log "04: inventory endpoint reachable"
for _ in $(seq 1 30); do
  INV_RESPONSE="$(curl -sS -w '\n%{http_code}' -H "Authorization: Bearer $ACCESS_TOKEN" "$BASE_URL/inventory/stock" || true)"
  extract_status_and_body "$INV_RESPONSE"
  if [ "$HTTP_STATUS" = "200" ]; then
    break
  fi
  sleep 2
done
[ "$HTTP_STATUS" = "200" ] || fail "GET /inventory/stock returned HTTP $HTTP_STATUS. Body: $HTTP_BODY"

log "04: verify stock update from consumed event"
FOUND_STOCK=""
for _ in $(seq 1 40); do
  INV_RESPONSE="$(curl -sS -w '\n%{http_code}' -H "Authorization: Bearer $ACCESS_TOKEN" "$BASE_URL/inventory/stock" || true)"
  extract_status_and_body "$INV_RESPONSE"
  [ "$HTTP_STATUS" = "200" ] || fail "GET /inventory/stock returned HTTP $HTTP_STATUS. Body: $HTTP_BODY"

  FOUND_STOCK="$(printf '%s' "$HTTP_BODY" | python3 -c 'import json,sys; sku=sys.argv[1]; data=json.load(sys.stdin); print(next((str(i.get("stock")) for i in data.get("items",[]) if i.get("sku")==sku), ""))' "$ORDER_SKU")"

  if [ -n "$FOUND_STOCK" ]; then
    if [[ "$FOUND_STOCK" =~ ^[0-9]+$ ]] && [ "$FOUND_STOCK" -le 99 ]; then
      break
    fi
  fi
  sleep 2
done

[ -n "$FOUND_STOCK" ] || fail "SKU $ORDER_SKU not found in inventory snapshot"
[[ "$FOUND_STOCK" =~ ^[0-9]+$ ]] || fail "Invalid stock value for $ORDER_SKU: $FOUND_STOCK"
[ "$FOUND_STOCK" -le 99 ] || fail "Stock was not reduced for $ORDER_SKU. Current: $FOUND_STOCK"

log "04: inventory tests passed (stock=$FOUND_STOCK)"
