#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"

log() {
  echo "[tests] $*"
}

fail() {
  echo "[tests][ERROR] $*" >&2
  exit 1
}

extract_status_and_body() {
  local response="$1"
  HTTP_STATUS="$(printf '%s' "$response" | tail -n1)"
  HTTP_BODY="$(printf '%s' "$response" | sed '$d')"
}

log "Checking gateway health endpoint"
HEALTH_STATUS=""
for _ in $(seq 1 40); do
  HEALTH_STATUS="$(curl -sS -o /dev/null -w '%{http_code}' "$BASE_URL/" || true)"
  if [ "$HEALTH_STATUS" = "200" ]; then
    break
  fi
  sleep 2
done
[ "$HEALTH_STATUS" = "200" ] || fail "GET / returned HTTP $HEALTH_STATUS"

RND="$(date +%s)"
USERNAME="ci_user_${RND}"
EMAIL="ci_${RND}@example.com"
PASSWORD="ChangeMe123!"

SIGNUP_PAYLOAD="$(cat <<JSON
{"username":"$USERNAME","email":"$EMAIL","password":"$PASSWORD","role":"user"}
JSON
)"

log "Signing up a test user"
for _ in $(seq 1 30); do
  SIGNUP_RESPONSE="$(curl -sS -w '\n%{http_code}' -X POST "$BASE_URL/auth/signup" -H 'Content-Type: application/json' -d "$SIGNUP_PAYLOAD" || true)"
  extract_status_and_body "$SIGNUP_RESPONSE"
  if [ "$HTTP_STATUS" = "200" ]; then
    break
  fi
  sleep 2
done
[ "$HTTP_STATUS" = "200" ] || fail "POST /auth/signup returned HTTP $HTTP_STATUS. Body: $HTTP_BODY"

ACCESS_TOKEN="$(printf '%s' "$HTTP_BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))')"
[ -n "$ACCESS_TOKEN" ] || fail "Signup response did not include access_token"

ORDER_PAYLOAD='{"items":[{"sku":"LAPTOP-01","qty":1}]}'
log "Creating order"
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

log "Polling order status for order_id=$ORDER_ID"
FINAL_STATUS=""
for _ in $(seq 1 30); do
  STATUS_RESPONSE="$(curl -sS -w '\n%{http_code}' -H "Authorization: Bearer $ACCESS_TOKEN" "$BASE_URL/orders/$ORDER_ID")"
  extract_status_and_body "$STATUS_RESPONSE"
  [ "$HTTP_STATUS" = "200" ] || fail "GET /orders/$ORDER_ID returned HTTP $HTTP_STATUS. Body: $HTTP_BODY"

  FINAL_STATUS="$(printf '%s' "$HTTP_BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))')"
  if [ "$FINAL_STATUS" = "PERSISTED" ]; then
    break
  fi
  sleep 2
done

[ "$FINAL_STATUS" = "PERSISTED" ] || fail "Order did not reach PERSISTED state. Last status: $FINAL_STATUS"

log "Checking inventory endpoint"
INVENTORY_STATUS="$(curl -sS -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $ACCESS_TOKEN" "$BASE_URL/inventory/stock")"
[ "$INVENTORY_STATUS" = "200" ] || fail "GET /inventory/stock returned HTTP $INVENTORY_STATUS"

log "Integration smoke tests passed"
