#!/usr/bin/env bash
set -euo pipefail

# Test 02: valida flujo de autenticacion completo (signup, me y refresh de token).

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/helpers.sh"

RND="$(date +%s)"
USERNAME="ci_user_${RND}"
EMAIL="ci_${RND}@example.com"
PASSWORD="ChangeMe123!"

SIGNUP_PAYLOAD="$(cat <<JSON
{"username":"$USERNAME","email":"$EMAIL","password":"$PASSWORD","role":"user"}
JSON
)"

log "02: signup"
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
REFRESH_TOKEN="$(printf '%s' "$HTTP_BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("refresh_token",""))')"
[ -n "$ACCESS_TOKEN" ] || fail "Signup response did not include access_token"
[ -n "$REFRESH_TOKEN" ] || fail "Signup response did not include refresh_token"

log "02: auth/me"
ME_RESPONSE="$(curl -sS -w '\n%{http_code}' -H "Authorization: Bearer $ACCESS_TOKEN" "$BASE_URL/auth/me" || true)"
extract_status_and_body "$ME_RESPONSE"
[ "$HTTP_STATUS" = "200" ] || fail "GET /auth/me returned HTTP $HTTP_STATUS. Body: $HTTP_BODY"
ME_USERNAME="$(printf '%s' "$HTTP_BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("username",""))')"
[ "$ME_USERNAME" = "$USERNAME" ] || fail "GET /auth/me returned unexpected username: $ME_USERNAME"

log "02: refresh token"
REFRESH_PAYLOAD="$(cat <<JSON
{"refresh_token":"$REFRESH_TOKEN"}
JSON
)"
REFRESH_RESPONSE="$(curl -sS -w '\n%{http_code}' -X POST "$BASE_URL/auth/refresh" -H 'Content-Type: application/json' -d "$REFRESH_PAYLOAD" || true)"
extract_status_and_body "$REFRESH_RESPONSE"
[ "$HTTP_STATUS" = "200" ] || fail "POST /auth/refresh returned HTTP $HTTP_STATUS. Body: $HTTP_BODY"
NEW_ACCESS_TOKEN="$(printf '%s' "$HTTP_BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))')"
[ -n "$NEW_ACCESS_TOKEN" ] || fail "Refresh response did not include access_token"

upsert_state ACCESS_TOKEN "$NEW_ACCESS_TOKEN"
upsert_state USERNAME "$USERNAME"
upsert_state ORDER_SKU "LAPTOP-01"
upsert_state ORDER_QTY "1"

log "02: auth tests passed"
