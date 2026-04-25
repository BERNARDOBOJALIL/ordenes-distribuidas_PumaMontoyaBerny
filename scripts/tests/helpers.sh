#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
STATE_FILE="${STATE_FILE:-/tmp/distributed_orders_test_state.env}"

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

wait_for_http_200() {
  local url="$1"
  local attempts="$2"
  local sleep_seconds="$3"
  local code=""

  for _ in $(seq 1 "$attempts"); do
    code="$(curl -sS -o /dev/null -w '%{http_code}' "$url" || true)"
    if [ "$code" = "200" ]; then
      return 0
    fi
    sleep "$sleep_seconds"
  done

  fail "Endpoint not ready after retries: $url (last HTTP $code)"
}

upsert_state() {
  local key="$1"
  local value="$2"

  mkdir -p "$(dirname "$STATE_FILE")"
  touch "$STATE_FILE"

  if grep -q "^${key}=" "$STATE_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$STATE_FILE"
  else
    echo "${key}=${value}" >> "$STATE_FILE"
  fi
}

load_state() {
  [ -f "$STATE_FILE" ] || fail "State file not found: $STATE_FILE"
  # shellcheck disable=SC1090
  source "$STATE_FILE"
}
