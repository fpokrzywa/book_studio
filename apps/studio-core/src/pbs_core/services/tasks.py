"""Durable background tasks: non-AI work that can take minutes (publishing builds, packages, covers,
audio exports). They run in the worker, not in the web request, so a slow PDF build cannot hit a
proxy timeout and a server restart does not lose it.

* A task is a row in ``background_task``; the browser polls ``GET /api/tasks/{id}``.
* Claiming uses the same single-transaction pattern as AI jobs, so one task runs once at a time.
* On worker start, tasks left ``running`` are queued again (builds are idempotent: each attempt
  writes a new publication) or marked ``interrupted`` once attempts are used up.
* Errors are stored as the same problem code and title the synchronous endpoint would return.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import structlog
from pydantic import BaseModel
from sqlalchemy import select

from pbs_core.context import AppContext
from pbs_core.contracts_auth import TaskOut
from pbs_core.domain.errors import DomainError, NotFoundError
from pbs_core.storage.auth_models import BackgroundTask

log = structlog.get_logger(__name__)


def _build(ctx: AppContext, pid: str, inp: dict[str, Any]) -> BaseModel:
    from pbs_core.contracts_publishing import BuildIn
    from pbs_core.services import publishing

    return publishing.build(ctx, pid, BuildIn.model_validate(inp))


def _covers(ctx: AppContext, pid: str, _inp: dict[str, Any]) -> BaseModel:
    from pbs_core.services import publishing

    return publishing.build_covers(ctx, pid)


def _package(ctx: AppContext, pid: str, _inp: dict[str, Any]) -> BaseModel:
    from pbs_core.services import publishing

    return publishing.build_package(ctx, pid)


def _audio(ctx: AppContext, pid: str, _inp: dict[str, Any]) -> BaseModel:
    from pbs_core.services import media

    return media.export_audio(ctx, pid)


HANDLERS: dict[str, Callable[[AppContext, str, dict[str, Any]], BaseModel]] = {
    "publishing.build": _build,
    "publishing.covers": _covers,
    "publishing.package": _package,
    "narration.export": _audio,
}


def _out(row: BackgroundTask) -> TaskOut:
    return TaskOut(
        id=row.id,
        kind=row.kind,
        project_id=row.project_id,
        status=row.status,
        result=json.loads(row.result_json) if row.result_json else None,
        error_code=row.error_code,
        error_message=row.error_message,
        attempt=row.attempt,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def enqueue(ctx: AppContext, kind: str, project_id: str | None, inp: dict[str, Any] | None = None) -> TaskOut:
    if kind not in HANDLERS:
        raise ValueError(f"unknown task kind {kind}")
    with ctx.db.tx() as s:
        if project_id is not None:
            from pbs_core.services.projects import require_active

            require_active(s, project_id)  # 404 / 409 now, not later in the worker
        row = BackgroundTask(
            id=ctx.ids.new(),
            kind=kind,
            project_id=project_id,
            status="queued",
            input_json=json.dumps(inp or {}),
            created_at=ctx.clock.iso(),
        )
        s.add(row)
        s.flush()
        out = _out(row)
    if ctx.jobs is not None:
        ctx.jobs.wake()
    return out


def get(ctx: AppContext, task_id: str) -> TaskOut:
    with ctx.db.tx() as s:
        row = s.get(BackgroundTask, task_id)
        if row is None:
            raise NotFoundError("That background task does not exist.")
        return _out(row)


def claim(ctx: AppContext, owner: str) -> str | None:
    with ctx.db.tx() as s:
        row = s.scalars(
            select(BackgroundTask)
            .where(BackgroundTask.status == "queued")
            .order_by(BackgroundTask.created_at, BackgroundTask.id)
            .limit(1)
        ).first()
        if row is None:
            return None
        row.status, row.lease_owner = "running", owner
        row.attempt += 1
        row.started_at = row.started_at or ctx.clock.iso()
        return row.id


def run(ctx: AppContext, task_id: str) -> None:
    with ctx.db.tx() as s:
        row = s.get(BackgroundTask, task_id)
        if row is None or row.status != "running":
            return
        kind, pid, inp = row.kind, row.project_id or "", json.loads(row.input_json)
    status, result, code, message = "succeeded", None, None, None
    try:
        result = HANDLERS[kind](ctx, pid, inp).model_dump(mode="json")
    except DomainError as exc:
        status, code, message = "failed", exc.code, exc.title + (f" {exc.detail}" if exc.detail else "")
    except Exception as exc:
        log.exception("task_failed", task_id=task_id, kind=kind, error_type=type(exc).__name__)
        status, code, message = "failed", "internal_error", "The task failed unexpectedly. The error was logged."
    with ctx.db.tx() as s:
        row = s.get(BackgroundTask, task_id)
        if row is None:
            return
        row.status, row.error_code, row.error_message = status, code, message
        row.result_json = json.dumps(result) if result is not None else None
        row.finished_at, row.lease_owner = ctx.clock.iso(), None
    log.info("task_finished", task_id=task_id, kind=kind, status=status)


def run_once(ctx: AppContext, owner: str = "inline") -> bool:
    task_id = claim(ctx, owner)
    if task_id is None:
        return False
    run(ctx, task_id)
    return True


def recover(ctx: AppContext) -> int:
    n = 0
    with ctx.db.tx() as s:
        for row in s.scalars(select(BackgroundTask).where(BackgroundTask.status == "running")).all():
            n += 1
            row.lease_owner = None
            if row.attempt < row.max_attempts:
                row.status = "queued"
            else:
                row.status, row.finished_at = "interrupted", ctx.clock.iso()
                row.error_code = "interrupted"
                row.error_message = "The server stopped while this was running and no attempts are left. Try again."
    if n:
        log.info("tasks_recovered", count=n)
    return n
