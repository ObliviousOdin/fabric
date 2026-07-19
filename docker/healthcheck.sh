#!/bin/sh
# docker/healthcheck.sh — container HEALTHCHECK probe for the Fabric image
# family (Dockerfile.fabric / .fabric-lite / .fabric-cloud).
#
# Probes whichever HTTP surface this container is configured to serve:
#
#   1. API server enabled (API_SERVER_ENABLED truthy — always true in the
#      lite/cloud images): GET /health on the API-server port must return
#      2xx. Port resolution mirrors the lite entrypoint: API_SERVER_PORT
#      first, then Cloud Run's $PORT, then the engine default 8642.
#   2. No HTTP surface enabled (e.g. `docker run fabric chat`): exit 0 —
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
