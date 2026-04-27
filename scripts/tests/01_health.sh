#!/usr/bin/env bash
set -euo pipefail

# Test 01: valida disponibilidad inicial del API Gateway (health basico de arranque).

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/helpers.sh"

log "01: waiting for API Gateway root endpoint"
wait_for_http_200 "$BASE_URL/" 40 2
log "01: gateway is reachable"
