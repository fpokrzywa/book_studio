#!/usr/bin/env bash
# Whole-studio backup: every book, revision, original, asset, export, recording, setting, account
# and queued job (the data folder), checked after writing. The studio stops for the few seconds
# the copy takes, so the database and the files are consistent.
#
#   sudo deploy/scripts/backup.sh [--label nightly] [--keep 14] [--path-file FILE]
#
# --keep N deletes the oldest studio-*.tar.gz backups in PBS_BACKUP_DIR beyond the newest N.
# The master key is NOT in the archive (keep it separately: docs/OPERATIONS.md, "Backups").
. "$(dirname "$0")/common.sh"

LABEL="manual" KEEP="" PATH_FILE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --label) LABEL="$(printf '%s' "$2" | tr -c 'A-Za-z0-9._-' '-')"; shift 2 ;;
    --keep) KEEP="$2"; shift 2 ;;
    --path-file) PATH_FILE="$2"; shift 2 ;; # write the new archive's path here (for update.sh)
    *) die "unknown option $1" ;;
  esac
done
need_root; require_env
[ -z "$KEEP" ] || [[ "$KEEP" =~ ^[1-9][0-9]*$ ]] || die "--keep needs a number of at least 1"

NAME="studio-$(date -u +%Y%m%dT%H%M%SZ)-$LABEL.tar.gz"
OUT="$BACKUP_DIR/$NAME"
[ -e "$OUT" ] && die "$OUT already exists"

was_running=0
if [ -n "$(compose ps -q --status running app 2>/dev/null)" ]; then
  was_running=1
  log "stopping app and worker for a consistent copy"
  compose stop worker app >/dev/null
fi
restart_services() {
  if [ "$was_running" = 1 ]; then
    log "starting app and worker"
    compose start app worker >/dev/null
  fi
}
trap 'restart_services' ERR

log "writing $OUT"
tar --create --gzip --file "$OUT.partial" --directory "$DATA_DIR" \
  --exclude=./runtime/tmp --exclude=./runtime/worker.lock --exclude=./runtime/worker.heartbeat .
chmod 600 "$OUT.partial"
mv "$OUT.partial" "$OUT"
trap - ERR
restart_services
if [ "$was_running" = 1 ]; then wait_healthy; fi

log "verifying the archive"
if ! compose run --rm --no-deps -T --user 0 -v "$BACKUP_DIR:/backups:ro" app verify-backup "/backups/$NAME" \
  > "$OUT.manifest.json" </dev/null; then
  die "the new backup failed verification: $OUT (see $OUT.manifest.json)"
fi
(cd "$BACKUP_DIR" && sha256sum "$NAME" > "$NAME.sha256")
chmod 600 "$OUT.manifest.json" "$OUT.sha256"

if [ -n "$KEEP" ]; then
  mapfile -t old < <(ls -1t "$BACKUP_DIR"/studio-*.tar.gz 2>/dev/null | tail -n +"$((KEEP + 1))")
  for f in "${old[@]}"; do
    log "removing old backup $(basename "$f")"
    rm -f -- "$f" "$f.sha256" "$f.manifest.json"
  done
fi
log "backup OK: $OUT ($(du -h "$OUT" | cut -f1))"
echo "BACKUP=$OUT"
if [ -n "$PATH_FILE" ]; then printf '%s
' "$OUT" > "$PATH_FILE"; fi
