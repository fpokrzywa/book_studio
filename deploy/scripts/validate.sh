#!/usr/bin/env bash
# Deployment validation: containers healthy, database and folders sound, nothing published that
# should not be, and (with --url) the studio answering through Nginx Proxy Manager over HTTPS.
#
#   sudo deploy/scripts/validate.sh [--url https://books.example.com] [--cacert ca.pem | --insecure]
#        [--resolve host:443:ip]
. "$(dirname "$0")/common.sh"

URL=""
CURL_OPTS=(-sS --max-time 15)
while [ $# -gt 0 ]; do
  case "$1" in
    --url) URL="${2%/}"; shift 2 ;;
    --insecure) CURL_OPTS+=(-k); shift ;;
    --cacert) CURL_OPTS+=(--cacert "$2"); shift 2 ;;
    --resolve) CURL_OPTS+=(--resolve "$2"); shift 2 ;;
    *) die "unknown option $1" ;;
  esac
done
require_env
fail=0
pass() { log "PASS  $*"; }
bad() { log "FAIL  $*"; fail=1; }

for svc in app worker; do
  id="$(compose ps -q "$svc" | head -n 1)"
  state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id" 2>/dev/null || echo missing)"
  if [ "$state" = "healthy" ]; then pass "$svc is healthy"; else bad "$svc is $state"; fi
done
if compose exec -T app python -m pbs_core check; then pass "database, schema, folders, disk"; else bad "core check"; fi

ports="$(docker port "$(compose ps -q app | head -n 1)" 2>/dev/null || true)"
if [ -n "$(env_get PBS_PUBLISH_HTTP)" ]; then
  if [ -n "$ports" ]; then pass "app published only as configured: $ports"; else bad "PBS_PUBLISH_HTTP is set but nothing is published"; fi
elif [ -z "$ports" ]; then
  pass "app publishes no host port (reachable only through the proxy network)"
else
  bad "app publishes $ports"
fi
for svc in worker ollama; do
  id="$(compose ps -q "$svc" 2>/dev/null | head -n 1)"
  [ -z "$id" ] && continue
  if [ -z "$(docker port "$id" 2>/dev/null)" ]; then pass "$svc publishes no port"; else bad "$svc publishes a port"; fi
done

if [ "$(env_get PBS_TRUSTED_PROXIES_AUTO 0)" = "1" ]; then
  NET="$(env_get PBS_PROXY_NETWORK npm_proxy)"
  SUBNET="$(docker network inspect -f '{{range .IPAM.Config}}{{.Subnet}} {{end}}' "$NET" 2>/dev/null | awk '{print $1}')"
  if [ -n "$SUBNET" ] && [ "$(env_get PBS_TRUSTED_PROXIES)" = "[\"$SUBNET\"]" ]; then pass "trusted proxy subnet matches $NET ($SUBNET)"
  else bad "PBS_TRUSTED_PROXIES does not match the $NET network ($SUBNET): run install.sh again"; fi
fi

if [ "$(id -u)" -eq 0 ]; then
  if [ "$(stat -c '%u %a' "$DATA_DIR")" = "$APP_UID 700" ]; then pass "data folder owned by $APP_UID, mode 700"
  else bad "data folder ownership/mode is $(stat -c '%u %a' "$DATA_DIR") (want $APP_UID 700)"; fi
  KEY="$(env_get PBS_MASTER_KEY_FILE)"
  if [ "$(stat -c '%u %a' "$KEY" 2>/dev/null)" = "$APP_UID 400" ]; then pass "master key mode 400"
  else bad "master key $KEY missing or not mode 400"; fi
fi

if [ -n "$URL" ]; then
  code="$(curl "${CURL_OPTS[@]}" -o /dev/null -w '%{http_code}' "$URL/healthz" || true)"
  if [ "$code" = 200 ]; then pass "$URL/healthz answers through the proxy"; else bad "$URL/healthz returned $code"; fi
  code="$(curl "${CURL_OPTS[@]}" -o /dev/null -w '%{http_code}' "$URL/api/projects" || true)"
  if [ "$code" = 401 ]; then pass "the API refuses requests without a sign-in"; else bad "$URL/api/projects returned $code (want 401)"; fi
  hdr="$(curl "${CURL_OPTS[@]}" -D - -o /dev/null "$URL/" || true)"
  if printf '%s' "$hdr" | grep -qi '^strict-transport-security:'; then pass "HSTS header present"; else bad "no HSTS header"; fi
  if printf '%s' "$hdr" | grep -qi "^content-security-policy:.*frame-ancestors 'none'"; then pass "CSP header present"; else bad "no CSP header"; fi
fi
if [ "$fail" = 0 ]; then log "validation PASSED"; else log "validation FAILED"; fi
exit "$fail"
