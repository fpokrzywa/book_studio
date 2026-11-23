#!/usr/bin/env bash
# Background job monitoring: queued, running and failed AI jobs and build/export tasks, the age of
# the oldest queued item and the worker's last heartbeat. Add --json for scripts.
#
#   sudo deploy/scripts/status.sh [--json]
. "$(dirname "$0")/common.sh"
require_env
compose ps
compose exec -T app python -m pbs_core status "$@"
