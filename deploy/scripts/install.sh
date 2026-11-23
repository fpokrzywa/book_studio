#!/usr/bin/env bash
# First installation on Ubuntu (docs/DEPLOYMENT.md §2). Safe to run again: it never overwrites
# deploy/.env, the master key or any data.
#
#   sudo deploy/scripts/install.sh --domain books.example.com [--data-root /srv/book-studio]
#        [--proxy-network npm_proxy] [--publish 192.168.1.20:8765 --trusted-proxy 192.168.1.10]
#        [--ollama docker|none] [--no-cloud]
. "$(dirname "$0")/common.sh"

DOMAIN="" ROOT="/srv/book-studio" NET="npm_proxy" PUBLISH="" TRUSTED="" OLLAMA="" NOCLOUD=0
while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2 ;;
    --data-root) ROOT="$2"; shift 2 ;;
    --proxy-network) NET="$2"; shift 2 ;;
    --publish) PUBLISH="$2"; shift 2 ;;
    --trusted-proxy) TRUSTED="$2"; shift 2 ;;
    --ollama) OLLAMA="$2"; shift 2 ;;
    --no-cloud) NOCLOUD=1; shift ;;
    *) die "unknown option $1 (see the top of this script)" ;;
  esac
done

need_root
need_cmd docker "Install Docker Engine: https://docs.docker.com/engine/install/ubuntu/"
docker compose version >/dev/null 2>&1 || die "the Docker Compose plugin is missing (apt install docker-compose-plugin)"
need_cmd openssl "apt install openssl"

if [ ! -f "$ENV_FILE" ]; then
  [ -n "$DOMAIN" ] || die "first install needs --domain (the name people will type, e.g. books.example.com)"
  install -m 600 "$DEPLOY_DIR/.env.example" "$ENV_FILE"
  env_set PBS_DOMAIN "$DOMAIN"
  env_set PBS_PROXY_NETWORK "$NET"
  env_set PBS_DATA_DIR "$ROOT/data"
  env_set PBS_BACKUP_DIR "$ROOT/backups"
  env_set PBS_MASTER_KEY_FILE "$ROOT/secrets/pbs_master_key"
  env_set PBS_OLLAMA_DIR "$ROOT/ollama"
  [ -n "$PUBLISH" ] && env_set PBS_PUBLISH_HTTP "$PUBLISH"
  [ -n "$TRUSTED" ] && env_set PBS_TRUSTED_PROXIES "[\"$TRUSTED\"]"
  [ -n "$OLLAMA" ] && env_set PBS_OLLAMA "$OLLAMA"
  [ "$NOCLOUD" = 1 ] && env_set PBS_ALLOW_CLOUD false
  log "created $ENV_FILE"
else
  log "keeping the existing $ENV_FILE"
fi
require_env
KEY="$(env_get PBS_MASTER_KEY_FILE)"; OLLAMA_DIR="$(env_get PBS_OLLAMA_DIR)"; NET="$(env_get PBS_PROXY_NETWORK npm_proxy)"

# Folders: data belongs to the studio's user; backups and the key folder to root only.
install -d -m 700 -o "$APP_UID" -g "$APP_UID" "$DATA_DIR"
install -d -m 700 -o root -g root "$BACKUP_DIR" "$(dirname "$KEY")"
[ "$(env_get PBS_OLLAMA none)" = "docker" ] && install -d -m 755 "$OLLAMA_DIR"
if [ ! -s "$KEY" ]; then
  ( umask 077; openssl rand -base64 32 > "$KEY" )
  log "created the master key $KEY. Copy it somewhere safe, apart from your backups."
fi
chown "$APP_UID:$APP_UID" "$KEY"; chmod 400 "$KEY"   # the containers read it as uid $APP_UID

# The network Nginx Proxy Manager shares with the app.
if ! docker network inspect "$NET" >/dev/null 2>&1; then
  docker network create "$NET" >/dev/null
  log "created Docker network $NET. Connect Nginx Proxy Manager to it: docker network connect $NET <npm-container>"
fi
# "auto" (and every later run, while PBS_TRUSTED_PROXIES_AUTO=1): trust the proxy network's subnet,
# re-read each time because a recreated network can get a different subnet.
if [ "$(env_get PBS_TRUSTED_PROXIES auto)" = "auto" ] || [ "$(env_get PBS_TRUSTED_PROXIES_AUTO 0)" = "1" ]; then
  SUBNET="$(docker network inspect -f '{{range .IPAM.Config}}{{.Subnet}} {{end}}' "$NET" | awk '{print $1}')"
  [ -n "$SUBNET" ] || die "could not read the subnet of $NET; set PBS_TRUSTED_PROXIES in $ENV_FILE"
  env_set PBS_TRUSTED_PROXIES "[\"$SUBNET\"]"
  env_set PBS_TRUSTED_PROXIES_AUTO 1
  log "trusting forwarded headers from $SUBNET (the $NET network)"
fi

TAG="$(git_revision)"
env_set PBS_IMAGE_TAG "$TAG"
log "building personal-book-studio:$TAG (several minutes the first time)"
compose build app
log "migrating the database"
core_run migrate
compose up -d
wait_healthy
"$DEPLOY_DIR/scripts/validate.sh" || die "validation failed (see above)"

if [ -f "$DATA_DIR/runtime/setup-code.txt" ]; then
  log "Next: in Nginx Proxy Manager add a proxy host for $(env_get PBS_DOMAIN) -> http://book-studio-app:8765 (docs/DEPLOYMENT.md §3)."
  log "Then open https://$(env_get PBS_DOMAIN) and create the account with this setup code:"
  log "  sudo cat $DATA_DIR/runtime/setup-code.txt"
fi
