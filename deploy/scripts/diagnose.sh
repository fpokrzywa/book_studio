#!/usr/bin/env bash
# Collect what is needed to understand a problem. Logs are already redacted (no keys, passwords or
# manuscript text). Save it with: sudo deploy/scripts/diagnose.sh > diagnose.txt
. "$(dirname "$0")/common.sh"
require_env
section() { printf '\n===== %s =====\n' "$*"; }

section "versions"
docker version --format 'docker {{.Server.Version}}' || true
docker compose version || true
printf 'image tag %s, code %s\n' "$(env_get PBS_IMAGE_TAG)" "$(git_revision)"
section "containers"
compose ps -a || true
section "health detail"
for svc in app worker; do
  id="$(compose ps -q "$svc" | head -n 1)"
  [ -n "$id" ] || continue
  docker inspect -f "$svc: health exit codes {{if .State.Health}}{{range .State.Health.Log}}{{.ExitCode}} {{end}}{{end}}; restarts {{.RestartCount}}" "$id" || true
done
section "disk"
df -h "$DATA_DIR" "$BACKUP_DIR" 2>/dev/null || true
section "studio status"
compose exec -T app python -m pbs_core status || true
section "checks"
compose exec -T app python -m pbs_core check || true
section "recent backups"
ls -lt "$BACKUP_DIR" 2>/dev/null | head -n 8 || true
section "app log (last 150 lines)"
compose logs --no-color --tail 150 app || true
section "worker log (last 150 lines)"
compose logs --no-color --tail 150 worker || true
