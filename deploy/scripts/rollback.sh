#!/usr/bin/env bash
# Undo the last update: go back to the previous image AND the backup taken just before the update
# (database changes are forward-only, so the old version needs the old data). Work saved after the
# update is not in that backup; the post-update data folder is kept aside by restore.sh, not deleted.
#
#   sudo deploy/scripts/rollback.sh [--yes]
. "$(dirname "$0")/common.sh"

YES=0
[ "${1-}" = "--yes" ] && YES=1
need_root; require_env
STATE="$BACKUP_DIR/last-update.env"
[ -f "$STATE" ] || die "no update to roll back ($STATE is missing)"
PREV_TAG="$(sed -n 's/^PREV_TAG=//p' "$STATE")"
BACKUP="$(sed -n 's/^PRE_UPDATE_BACKUP=//p' "$STATE")"
docker image inspect "personal-book-studio:$PREV_TAG" >/dev/null 2>&1 \
  || die "image personal-book-studio:$PREV_TAG is gone. Check out that revision and run update.sh instead."
[ -f "$BACKUP" ] || die "the pre-update backup $BACKUP is missing"
log "rolling back to image $PREV_TAG with backup $BACKUP"
if [ "$YES" != 1 ]; then
  read -r -p "Work saved since the update will be set aside. Type ROLLBACK: " answer
  [ "$answer" = "ROLLBACK" ] || die "cancelled; nothing was changed"
fi
compose stop worker app >/dev/null
env_set PBS_IMAGE_TAG "$PREV_TAG"
"$DEPLOY_DIR/scripts/restore.sh" --yes "$BACKUP"
mv "$STATE" "$STATE.rolled-back-$(date -u +%Y%m%dT%H%M%SZ)"
log "rollback OK: running $PREV_TAG. Keep the code in step: git -C $REPO_DIR checkout $PREV_TAG"
