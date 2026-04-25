#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/helpers.sh"
load_state

[ -n "${ACCESS_TOKEN:-}" ] || fail "ACCESS_TOKEN missing in state"
[ -n "${ORDER_SKU:-}" ] || fail "ORDER_SKU missing in state"
[ -n "${ORDER_QTY:-}" ] || fail "ORDER_QTY missing in state"

ORDER_PAYLOAD="$(cat <<JSON
{"items":[{"sku":"$ORDER_SKU","qty":$ORDER_QTY}]}
JSON
)"

log "03: create order"
for _ in $(seq 1 30); do
  ORDER_RESPONSE="$(curl -sS -w '\n%{http_code}' -X POST "$BASE_URL/orders" -H 'Content-Type: application/json' -H "Authorization: Bearer $ACCESS_TOKEN" -d "$ORDER_PAYLOAD" || true)"
  extract_status_and_body "$ORDER_RESPONSE"
  if [ "$HTTP_STATUS" = "202" ]; then
    break
  fi
  sleep 2
done
[ "$HTTP_STATUS" = "202" ] || fail "POST /orders returned HTTP $HTTP_STATUS. Body: $HTTP_BODY"

ORDER_ID="$(printf '%s' "$HTTP_BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("order_id",""))')"
[ -n "$ORDER_ID" ] || fail "Order response did not include order_id"
upsert_state ORDER_ID "$ORDER_ID"

log "03: poll order status order_id=$ORDER_ID"
FINAL_STATUS=""
for _ in $(seq 1 40); do
  STATUS_RESPONSE="$(curl -sS -w '\n%{http_code}' -H "Authorization: Bearer $ACCESS_TOKEN" "$BASE_URL/orders/$ORDER_ID" || true)"
  extract_status_and_body "$STATUS_RESPONSE"
  if [ "$HTTP_STATUS" = "200" ]; then
    FINAL_STATUS="$(printf '%s' "$HTTP_BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))')"
    if [ "$FINAL_STATUS" = "PERSISTED" ]; then
      break
    fi
  fi
  sleep 2
done

[ "$FINAL_STATUS" = "PERSISTED" ] || fail "Order did not reach PERSISTED. Last status: $FINAL_STATUS"
log "03: order flow tests passed"
