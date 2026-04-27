#!/usr/bin/env bash
set -euo pipefail

# Orquesta la suite de integracion distribuida y ejecuta los tests por fases.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TESTS_DIR="$SCRIPT_DIR/tests"

BASE_URL="${BASE_URL:-http://localhost:8000}"
STATE_FILE="${STATE_FILE:-/tmp/distributed_orders_test_state.env}"

echo "[tests] Running distributed integration suite"
echo "[tests] BASE_URL=$BASE_URL"

rm -f "$STATE_FILE"
export BASE_URL
export STATE_FILE

tests=(
  "01_health.sh"
  "02_auth.sh"
  "03_orders.sh"
  "04_inventory.sh"
  "05_notification.sh"
)

for test_script in "${tests[@]}"; do
  echo "[tests] Running $test_script"
  bash "$TESTS_DIR/$test_script"
done

echo "[tests] Distributed integration suite passed"
