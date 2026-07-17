#!/bin/sh
# docker/healthcheck.sh — container HEALTHCHECK probe for the Fabric image
# family (Dockerfile.fabric / .fabric-lite / .fabric-cloud).
#
# Probes whichever HTTP surface this container is configured to serve:
#
#   1. Dashboard enabled (FABRIC_DASHBOARD or FABRIC_DASHBOARD truthy):
#      the dashboard must answer HTTP on its port. Any status < 500 counts
#      as healthy — an auth-gated dashboard answers 401/302 while perfectly
#      alive, so `curl --fail` would be wrong here.
#   2. API server enabled (API_SERVER_ENABLED truthy — always true in the
#      lite/cloud images): GET /health on the API-server port must return
#      2xx. Port resolution mirrors the lite entrypoint: API_SERVER_PORT
#      first, then Cloud Run's $PORT, then the engine default 8642.
#   3. Neither surface enabled (e.g. `docker run fabric chat`): exit 0 —
#      there is nothing HTTP to probe, and process liveness is Docker's
#      own job.
#
# Exit 0 = healthy, exit 1 = unhealthy (Docker HEALTHCHECK contract).

set -u

truthy() {
    case "${1:-}" in
        1|true|TRUE|True|yes|YES|Yes) return 0 ;;
        *) return 1 ;;
    esac
}

fail() {
    echo "[healthcheck] $*" >&2
    exit 1
}

checked=0

# --- Dashboard probe -------------------------------------------------------
if truthy "${FABRIC_DASHBOARD:-}" || truthy "${FABRIC_DASHBOARD:-}"; then
    dash_port="${FABRIC_DASHBOARD_PORT:-${FABRIC_DASHBOARD_PORT:-9119}}"
    code="$(curl -s -o /dev/null -m 8 -w '%{http_code}' "http://127.0.0.1:${dash_port}/" || true)"
    case "$code" in
        "" | 000) fail "dashboard on 127.0.0.1:${dash_port} not answering" ;;
        [1-4]??) checked=1 ;;
        *) fail "dashboard on 127.0.0.1:${dash_port} returned HTTP ${code}" ;;
    esac
fi

# --- API-server probe ------------------------------------------------------
if truthy "${API_SERVER_ENABLED:-}"; then
    api_port="${API_SERVER_PORT:-${PORT:-8642}}"
    curl -fsS -m 8 -o /dev/null "http://127.0.0.1:${api_port}/health" \
        || fail "API server /health on 127.0.0.1:${api_port} failed"
    checked=1
fi

if [ "$checked" = 0 ]; then
    # No HTTP surface configured — nothing to probe.
    exit 0
fi

exit 0
