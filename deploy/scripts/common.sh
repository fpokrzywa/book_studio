#!/usr/bin/env bash
# Shared helpers for the Personal Book Studio operations scripts (docs/OPERATIONS.md).
# Rules every script follows: never remove Docker volumes or data folders, never overwrite a
# backup, and stop with a clear message instead of guessing.
set -Eeuo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="$(cd "$DEPLOY_DIR/.." && pwd)"
ENV_FILE="${PBS_ENV_FILE:-$DEPLOY_DIR/.env}"
APP_UID=10001

log() { printf '%s  %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
warn() { log "WARNING: $*" >&2; }
die() { log "ERROR: $*" >&2; exit 1; }

need_root() { [ "$(id -u)" -eq 0 ] || die "run this with sudo (it manages folders owned by the studio's user $APP_UID)"; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || die "'$1' is not installed. $2"; }

# Read KEY from deploy/.env literally (the file is not sourced: JSON values must keep their quotes).
env_get() {
  local key="$1" default="${2-}" line
  line="$(grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | tail -n 1 || true)"
  if [ -n "$line" ]; then printf '%s' "${line#*=}"; else printf '%s' "$default"; fi
}

# Set KEY=VALUE in deploy/.env (adds the line if missing). VALUE is written literally.
env_set() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp "$ENV_FILE.XXXXXX")"
  if grep -qE "^${key}=" "$ENV_FILE"; then
    awk -v k="$key" -v v="$value" 'BEGIN{FS=OFS="="} $1==k {print k "=" v; next} {print}' "$ENV_FILE" > "$tmp"
  else
    cat "$ENV_FILE" > "$tmp"; printf '%s=%s\n' "$key" "$value" >> "$tmp"
  fi
  chmod 600 "$tmp"; mv "$tmp" "$ENV_FILE"
}

require_env() {
  [ -f "$ENV_FILE" ] || die "$ENV_FILE is missing. Run deploy/scripts/install.sh first."
  DATA_DIR="$(env_get PBS_DATA_DIR)"; BACKUP_DIR="$(env_get PBS_BACKUP_DIR)"
  [ -n "$DATA_DIR" ] && [ -n "$BACKUP_DIR" ] || die "PBS_DATA_DIR and PBS_BACKUP_DIR must be set in $ENV_FILE"
}

compose() {
  local files=(-f "$DEPLOY_DIR/compose.yaml")
  [ -n "$(env_get PBS_PUBLISH_HTTP)" ] && files+=(-f "$DEPLOY_DIR/compose.publish.yaml")
  local profiles=()
  [ "$(env_get PBS_OLLAMA none)" = "docker" ] && profiles+=(--profile local-ai)
  # PBS_PROJECT_NAME lets a second, isolated copy run next to production (e.g. a restore rehearsal).
  docker compose --project-directory "$DEPLOY_DIR" --env-file "$ENV_FILE" -p "$(env_get PBS_PROJECT_NAME book-studio)"     "${files[@]}" "${profiles[@]}" "$@"
}

# Wait until app (and worker, if running) report healthy.
wait_healthy() {
  local deadline=$(( $(date +%s) + ${1:-180} )) svc state ok
  while [ "$(date +%s)" -lt "$deadline" ]; do
    ok=1
    for svc in app worker; do
      state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        "$(compose ps -q "$svc" 2>/dev/null | head -n 1)" 2>/dev/null || echo missing)"
      [ "$state" = "healthy" ] || ok=0
    done
    [ "$ok" = 1 ] && { log "app and worker are healthy"; return 0; }
    sleep 3
  done
  compose ps || true
  die "app and worker did not become healthy in time (see: deploy/scripts/diagnose.sh)"
}

# Run a Core command in a one-off container of the CURRENT image (works while the stack is stopped).
# stdin is closed so a one-off container never swallows input meant for the calling script (cron, pipes).
core_run() { compose run --rm --no-deps -T app "$@" </dev/null; }

git_revision() { git -C "$REPO_DIR" rev-parse --short=12 HEAD 2>/dev/null || date -u +%Y%m%d%H%M%S; }
