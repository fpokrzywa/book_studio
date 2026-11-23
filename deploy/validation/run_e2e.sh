#!/usr/bin/env bash
# End-to-end validation of a running deployment (docs/OPERATIONS.md, "End-to-end validation").
# It adds a book titled "Validation <date>" (and briefly a "Created after the backup" book, which
# the restore removes); archive or delete the validation book afterwards if you like.
# Do not use the studio while it runs: its last step restores the backup it took a minute earlier, so
# anything saved in between is set aside (data.pre-restore-*), not kept in the live studio.
#
#   sudo deploy/validation/run_e2e.sh --url https://books.example.com --username author \
#        --password-file /root/pbs-password [--cafile ca.pem | --insecure] \
#        [--ollama-url http://ollama:11434] [--model qwen2.5:0.5b]
#
# Steps: sign-in and access checks, import, structure and assets, AI-assisted edit, approval, new
# revision, DOCX/EPUB/PDF export, service restart, full container recreation, backup, a change made
# after the backup, restore, and checks that everything recorded before is still identical.
# It uses backup.sh and restore.sh, so the studio stops briefly twice.
. "$(dirname "$0")/../scripts/common.sh"

ARGS=()
while [ $# -gt 0 ]; do ARGS+=("$1"); shift; done
need_root; require_env
need_cmd python3 "apt install python3"
WORK="$(mktemp -d)"
chmod 700 "$WORK"
cleanup() { rm -f "$WORK/state.json" "$WORK/state.cookies"; }
trap cleanup EXIT
E2E=(python3 "$DEPLOY_DIR/validation/e2e_validate.py" --state "$WORK/state.json" "${ARGS[@]}")

log "1/7 writing the representative manuscript (in the studio image)"
compose run --rm --no-deps -T --entrypoint python app - < "$DEPLOY_DIR/validation/make_manuscript.py" \
  > "$WORK/lighthouse-ledger.docx"

log "2/7 workflow: sign-in, import, AI edit, approval, revision, exports"
"${E2E[@]}" workflow --manuscript "$WORK/lighthouse-ledger.docx" \
  --setup-code-file "$DATA_DIR/runtime/setup-code.txt"

log "3/7 restarting app and worker"
compose restart app worker >/dev/null
wait_healthy
"${E2E[@]}" verify --label "after restart"

log "4/7 recreating every container (as an update does)"
compose down >/dev/null   # no -v: data lives in host folders and is never removed
compose up -d >/dev/null
wait_healthy
"${E2E[@]}" verify --label "after recreating containers"

log "5/7 backup"
"$DEPLOY_DIR/scripts/backup.sh" --label e2e --path-file "$WORK/backup.path"
BACKUP="$(cat "$WORK/backup.path")"
[ -n "$BACKUP" ] || die "backup failed"

log "6/7 a change after the backup, then restore"
"${E2E[@]}" marker
"$DEPLOY_DIR/scripts/restore.sh" --yes "$BACKUP"

log "7/7 checks after the restore"
"${E2E[@]}" verify-restore
log "END-TO-END VALIDATION PASSED (backup used: $BACKUP)"
