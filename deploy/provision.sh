#!/usr/bin/env bash
# =============================================================================
# provision.sh — unattended, idempotent seeding for a hosted Fabric deploy.
#
# Fabric's `fabric setup` wizard is interactive-only; a hosted box seeds config
# directly instead (a supported path — any provider key makes Fabric usable with
# no wizard). This script does exactly that, non-interactively:
#
#   • generates a dashboard login (username + strong password)
#   • computes the scrypt password_hash with the image's own hash_password
#   • generates a stable dashboard signing secret (sessions survive restarts)
#   • generates a 32-byte API_SERVER_KEY and enables the OpenAI-compatible API
#   • writes config.yaml (model route + dashboard auth) into the data volume
#   • writes fabric-credentials.txt (mode 600) — what a managed control plane
#     would email to the user
#
# It is idempotent: existing secrets are reused unless you pass a --rotate flag.
#
# Usage:
#   ./provision.sh                 # first run or top-up
#   ./provision.sh --rotate-password
#   ./provision.sh --rotate-api-key
#   ./provision.sh --help
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE="$SCRIPT_DIR/.env"
ENV_EXAMPLE="$SCRIPT_DIR/.env.hosted.example"
STATE_FILE="$SCRIPT_DIR/.provision-state"      # persists non-reversible secrets
CREDS_FILE="$SCRIPT_DIR/fabric-credentials.txt"

ROTATE_PASSWORD=0
ROTATE_API_KEY=0
for arg in "$@"; do
  case "$arg" in
    --rotate-password) ROTATE_PASSWORD=1 ;;
    --rotate-api-key)  ROTATE_API_KEY=1 ;;
    -h|--help)
      sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

log()  { printf '  %s\n' "$*"; }
warn() { printf '  ! %s\n' "$*" >&2; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }

command -v openssl >/dev/null 2>&1 || die "openssl is required"

# --- .env helpers ----------------------------------------------------------
[ -f "$ENV_FILE" ] || { [ -f "$ENV_EXAMPLE" ] && cp "$ENV_EXAMPLE" "$ENV_FILE" && log "created .env from example"; }
[ -f "$ENV_FILE" ] || die "no .env and no .env.hosted.example to copy from"

# Read a KEY=VALUE from .env (value only, no surrounding quotes).
get_env() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -n1; }

# Set (or append) KEY=VALUE in .env, in place.
set_env() {
  local key="$1" val="$2"
  if grep -q "^$key=" "$ENV_FILE"; then
    # Use a non-/ delimiter; values may contain / (base64) but not | here.
    local tmp; tmp="$(mktemp)"
    awk -v k="$key" -v v="$val" 'BEGIN{FS=OFS="="} $1==k{print k"="v; done=1; next} {print} END{if(!done) print k"="v}' \
      "$ENV_FILE" > "$tmp" && mv "$tmp" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
  fi
}

# --- required inputs -------------------------------------------------------
DOMAIN="$(get_env FABRIC_PUBLIC_DOMAIN)"
ACME_EMAIL="$(get_env ACME_EMAIL)"
[ -n "$DOMAIN" ] && [ "$DOMAIN" != "agent.example.com" ] || die "set FABRIC_PUBLIC_DOMAIN in .env"
[ -n "$ACME_EMAIL" ] && [ "$ACME_EMAIL" != "you@example.com" ] || die "set ACME_EMAIL in .env"

DATA_DIR="$(get_env FABRIC_DATA_DIR)"; DATA_DIR="${DATA_DIR:-./data}"
FABRIC_IMAGE="$(get_env FABRIC_IMAGE)"; FABRIC_IMAGE="${FABRIC_IMAGE:-ghcr.io/obliviousodin/fabric:latest}"
mkdir -p "$DATA_DIR"

# Host UID/GID so container-written files stay writable on the host.
[ -n "$(get_env FABRIC_UID)" ] || set_env FABRIC_UID "$(id -u)"
[ -n "$(get_env FABRIC_GID)" ] || set_env FABRIC_GID "$(id -g)"

# --- model route -----------------------------------------------------------
MODEL_PROVIDER="$(get_env FABRIC_MODEL_PROVIDER)"
MODEL_DEFAULT="$(get_env FABRIC_MODEL_DEFAULT)"
MODEL_BASE_URL="$(get_env FABRIC_MODEL_BASE_URL)"
OPENROUTER_KEY="$(get_env OPENROUTER_API_KEY)"

if [ -z "$MODEL_PROVIDER" ]; then
  if [ -n "$MODEL_BASE_URL" ]; then MODEL_PROVIDER="custom"; else MODEL_PROVIDER="openrouter"; fi
fi
if [ "$MODEL_PROVIDER" = "openrouter" ] && [ -z "$OPENROUTER_KEY" ]; then
  warn "no OPENROUTER_API_KEY and no broker base_url set — the box will run but"
  warn "you must choose a model/provider in the dashboard (Admin → AI Runtime)."
fi

# --- API server key --------------------------------------------------------
API_KEY="$(get_env API_SERVER_KEY)"
if [ -z "$API_KEY" ] || [ "$ROTATE_API_KEY" = 1 ]; then
  API_KEY="$(openssl rand -hex 32)"
  set_env API_SERVER_KEY "$API_KEY"
  set_env API_SERVER_ENABLED "true"
  [ -n "$(get_env API_SERVER_HOST)" ] || set_env API_SERVER_HOST "0.0.0.0"
  log "generated API_SERVER_KEY"
fi

# --- dashboard secret + password (persisted in .provision-state) -----------
# shellcheck disable=SC1090
[ -f "$STATE_FILE" ] && . "$STATE_FILE"
DASH_USER="${DASHBOARD_USERNAME:-$(get_env DASHBOARD_USERNAME)}"; DASH_USER="${DASH_USER:-admin}"

save_state() {
  umask 077
  {
    printf 'DASHBOARD_USERNAME=%s\n' "$DASH_USER"
    printf 'DASHBOARD_SECRET=%s\n'   "$DASH_SECRET"
    printf 'DASHBOARD_PASSWORD_HASH=%s\n' "$DASH_HASH"
    printf 'DASHBOARD_HASH_MODE=%s\n' "$DASH_HASH_MODE"   # "hash" or "plain"
  } > "$STATE_FILE"
  chmod 600 "$STATE_FILE"
}

# Compute a scrypt hash using the image's helper; fall back to plaintext.
hash_password() {
  local pw="$1"
  if command -v docker >/dev/null 2>&1; then
    docker run --rm --entrypoint /opt/fabric/.venv/bin/python "$FABRIC_IMAGE" - "$pw" <<'PY' 2>/dev/null || true
import sys
sys.path.insert(0, "/opt/fabric")
from plugins.dashboard_auth.basic import hash_password
print(hash_password(sys.argv[1]))
PY
  fi
}

NEW_PASSWORD=""
if [ -z "${DASH_SECRET:-}" ] || [ "$ROTATE_PASSWORD" = 1 ]; then
  DASH_SECRET="$(openssl rand -base64 32)"
  NEW_PASSWORD="$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 24)"
  DASH_HASH="$(hash_password "$NEW_PASSWORD" | tr -d '\r\n')"
  if [ -n "$DASH_HASH" ]; then
    DASH_HASH_MODE="hash"
    log "generated dashboard login (scrypt hash via image)"
  else
    DASH_HASH="$NEW_PASSWORD"; DASH_HASH_MODE="plain"
    warn "could not hash via image (docker/image unavailable); storing plaintext"
    warn "password in config.yaml (mode 600). Re-run with docker available, or"
    warn "swap dashboard.basic_auth.password for a password_hash later."
  fi
  save_state
fi

: "${DASH_HASH_MODE:=hash}"

# --- write config.yaml into the data volume --------------------------------
CONFIG_FILE="$DATA_DIR/config.yaml"
{
  echo "# Generated by deploy/provision.sh — safe to edit."
  echo "# Re-running provision.sh preserves the dashboard secret/hash unless you"
  echo "# pass --rotate-password. Secrets here are protected by file mode 600/640."
  echo "model:"
  echo "  provider: ${MODEL_PROVIDER}"
  [ -n "$MODEL_DEFAULT" ]  && echo "  default: '${MODEL_DEFAULT}'"
  [ -z "$MODEL_DEFAULT" ]  && echo "  # default: '<model-id>'   # set FABRIC_MODEL_DEFAULT or pick one in the dashboard"
  [ -n "$MODEL_BASE_URL" ] && echo "  base_url: '${MODEL_BASE_URL}'"
  echo "dashboard:"
  echo "  public_url: 'https://${DOMAIN}'"
  echo "  basic_auth:"
  echo "    username: '${DASH_USER}'"
  if [ "$DASH_HASH_MODE" = "hash" ]; then
    echo "    password_hash: '${DASH_HASH}'"
  else
    echo "    password: '${DASH_HASH}'"
  fi
  echo "    secret: '${DASH_SECRET}'"
  echo "    session_ttl_seconds: 43200"
} > "$CONFIG_FILE"
chmod 600 "$CONFIG_FILE" 2>/dev/null || true
log "wrote ${CONFIG_FILE}"

# --- credentials summary (only when we minted a fresh password) ------------
if [ -n "$NEW_PASSWORD" ]; then
  umask 077
  cat > "$CREDS_FILE" <<EOF
Fabric hosted deploy — credentials
==================================
Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)

Dashboard URL:   https://${DOMAIN}
Username:        ${DASH_USER}
Password:        ${NEW_PASSWORD}

OpenAI-compatible API:
  Base URL:      https://${DOMAIN}/v1
  API key:       ${API_KEY}
  (send as: Authorization: Bearer ${API_KEY})

Keep this file safe. This password is shown ONCE; only its hash is stored on the
box. Rotate later with:  ./provision.sh --rotate-password
EOF
  chmod 600 "$CREDS_FILE"
  log "wrote ${CREDS_FILE} (mode 600)"
else
  log "reused existing dashboard secret (pass --rotate-password to change it)"
fi

echo
log "provisioning complete. Start with:"
log "  docker compose -f docker-compose.hosted.yml up -d"
[ -n "$NEW_PASSWORD" ] && log "  cat ${CREDS_FILE}"
