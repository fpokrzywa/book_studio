#!/usr/bin/env bash
# Restore a whole-studio backup. Nothing is deleted: the current data folder is moved aside to
# <data>.pre-restore-<time> and kept until you remove it yourself.
#
#   sudo deploy/scripts/restore.sh /srv/book-studio/backups/studio-...tar.gz [--yes]
. "$(dirname "$0")/common.sh"

ARCHIVE="" YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) YES=1; shift ;;
    -*) die "unknown option $1" ;;
    *) ARCHIVE="$1"; shift ;;
  esac
done
need_root; require_env
[ -n "$ARCHIVE" ] || die "say which backup to restore (sudo ls $BACKUP_DIR)"
ARCHIVE="$(readlink -f "$ARCHIVE")"
[ -f "$ARCHIVE" ] || die "$ARCHIVE does not exist"
if [ -f "$ARCHIVE.sha256" ]; then
  (cd "$(dirname "$ARCHIVE")" && sha256sum -c --quiet "$(basename "$ARCHIVE").sha256") \
    || die "checksum mismatch: $ARCHIVE; nothing was changed"
fi

log "verifying $ARCHIVE with the current image"
if ! REPORT="$(compose run --rm --no-deps -T --user 0 -v "$(dirname "$ARCHIVE"):/restore-src:ro" app \
  verify-backup "/restore-src/$(basename "$ARCHIVE")" </dev/null)"; then
  die "this backup is not usable; nothing was changed"
fi
printf '%s\n' "$REPORT"
printf '%s' "$REPORT" | grep -q '"restorable_by_this_version": true' \
  || die "the backup is from a newer version than this image; update first; nothing was changed"

if [ "$YES" != 1 ]; then
  read -r -p "Replace the current studio data with this backup? The current data is kept aside. Type RESTORE: " answer
  [ "$answer" = "RESTORE" ] || die "cancelled; nothing was changed"
fi

PREV="$DATA_DIR.pre-restore-$(date -u +%Y%m%dT%H%M%SZ)"
log "stopping app and worker"
compose stop worker app >/dev/null 2>&1 || true
if [ -e "$DATA_DIR" ] && [ -n "$(ls -A "$DATA_DIR" 2>/dev/null)" ]; then
  log "moving the current data to $PREV"
  mv "$DATA_DIR" "$PREV"
else
  log "no existing data at $DATA_DIR (a new server): restoring into an empty folder"
  [ -d "$DATA_DIR" ] && rmdir "$DATA_DIR"
  PREV="(none)"
fi
on_error() {
  log "Restore failed. Your previous data is untouched at $PREV. To put it back:"
  log "  sudo mv $DATA_DIR $DATA_DIR.failed-restore && sudo mv $PREV $DATA_DIR && sudo $DEPLOY_DIR/scripts/validate.sh"
}
trap on_error ERR
install -d -m 700 -o "$APP_UID" -g "$APP_UID" "$DATA_DIR"
tar --extract --gzip --file "$ARCHIVE" --directory "$DATA_DIR"
chown -R "$APP_UID:$APP_UID" "$DATA_DIR"
chmod 700 "$DATA_DIR"
log "starting the studio (it migrates the database if the backup is older)"
compose up -d >/dev/null
wait_healthy
"$DEPLOY_DIR/scripts/validate.sh"
trap - ERR
log "restore OK. The data from before the restore is kept at $PREV; remove it when you are satisfied."
