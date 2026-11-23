#!/usr/bin/env bash
# Update to the code in this checkout (or pull it first with --pull). Takes a verified backup,
# builds a new image next to the old one, migrates, starts and validates. Old images are kept so
# rollback.sh can return to them.
#
#   sudo deploy/scripts/update.sh [--pull]
. "$(dirname "$0")/common.sh"

PULL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --pull) PULL=1; shift ;;
    *) die "unknown option $1" ;;
  esac
done
need_root; require_env
OLD="$(env_get PBS_IMAGE_TAG local)"
if [ "$PULL" = 1 ]; then
  log "pulling the latest code"
  git -C "$REPO_DIR" pull --ff-only
fi
NEW="$(git_revision)"
log "updating from $OLD to $NEW"

PATH_FILE="$(mktemp)"
# Output goes straight to the caller's stdout/stderr (never through `tee /dev/stderr`, which reopens and
# truncates a log file the caller redirected to). The archive's path comes back through a file.
"$DEPLOY_DIR/scripts/backup.sh" --label "pre-update-$OLD" --path-file "$PATH_FILE" || true
BACKUP="$(cat "$PATH_FILE" 2>/dev/null || true)"
rm -f "$PATH_FILE"
[ -n "$BACKUP" ] || die "the pre-update backup failed; nothing was changed"
STATE="$BACKUP_DIR/last-update.env"
printf 'PREV_TAG=%s\nNEW_TAG=%s\nPRE_UPDATE_BACKUP=%s\nUPDATED_AT=%s\n' "$OLD" "$NEW" "$BACKUP" \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$STATE"
chmod 600 "$STATE"

env_set PBS_IMAGE_TAG "$NEW"
if ! compose build app; then
  env_set PBS_IMAGE_TAG "$OLD"
  die "the new image did not build; still running $OLD; nothing else was changed"
fi
log "stopping app and worker"
compose stop worker app >/dev/null
log "migrating the database (a snapshot is saved in the data folder first)"
if ! core_run migrate; then
  die "migration failed. Run: sudo deploy/scripts/rollback.sh (restores $BACKUP and image $OLD)"
fi
compose up -d >/dev/null
wait_healthy
"$DEPLOY_DIR/scripts/validate.sh" || die "validation failed after the update. Run: sudo deploy/scripts/rollback.sh"
log "update OK: now running $NEW (previous image $OLD kept; backup $BACKUP)"
