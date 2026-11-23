"""Durable job runner. Jobs live in SQLite; nothing exists only in memory.

* Claiming is a single `BEGIN IMMEDIATE` transaction, so two workers never take the same job.
* Concurrency is bounded (default 2 jobs at once; 1 per local Ollama server).
* On startup, jobs left `running` by a previous process are re-queued (or marked `interrupted`
  once their attempts are used up). The final commit is idempotent: a proposal is UNIQUE per job.
* Cancellation is cooperative: an in-memory event for instant response plus a DB flag that the
  worker re-reads while streaming, so a cancel from any process is honoured.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.domain.clock import to_iso
from pbs_core.storage.ai_models import Job, JobLog

log = structlog.get_logger(__name__)
LEASE_SECONDS = 300


def add_log(s: Session, ctx: AppContext, job_id: str, message: str, level: str = "info") -> None:
    s.add(JobLog(id=ctx.ids.new(), job_id=job_id, ts=ctx.clock.iso(), level=level, message=message[:2000]))


class JobRunner:
    def __init__(self, ctx: AppContext, *, workers: int = 2, poll_seconds: float = 0.5) -> None:
        self.ctx = ctx
        self.owner = f"core-{os.getpid()}-{ctx.ids.new()[-6:]}"
        self.poll_seconds = poll_seconds
        self._workers = threading.Semaphore(workers)
        self._ollama = threading.Semaphore(1)
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pbs-job")
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._cancel: dict[str, threading.Event] = {}
        self._cancel_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # ---------- lifecycle ----------
    def start(self) -> None:
        self.recover()
        self._thread = threading.Thread(target=self._loop, name="pbs-job-runner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        with self._cancel_lock:
            for ev in self._cancel.values():
                ev.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._pool.shutdown(wait=True, cancel_futures=True)

    def wake(self) -> None:
        self._wake.set()

    def recover(self) -> int:
        """Jobs a crashed or stopped process left running are run again or marked interrupted."""
        n = 0
        with self.ctx.db.tx() as s:
            for job in s.scalars(select(Job).where(Job.status == "running")).all():
                n += 1
                job.lease_owner = None
                job.lease_expires_at = None
                if job.cancel_requested:
                    job.status, job.stage, job.finished_at = "cancelled", "cancelled", self.ctx.clock.iso()
                    add_log(s, self.ctx, job.id, "Core restarted; the job had been cancelled.")
                elif job.attempt < job.max_attempts:
                    job.status, job.stage, job.run_after = "queued", "queued", self.ctx.clock.iso()
                    add_log(
                        s, self.ctx, job.id, "Core restarted while this job was running; it will run again.", "warning"
                    )
                else:
                    job.status, job.stage, job.finished_at = "interrupted", "interrupted", self.ctx.clock.iso()
                    job.error_code = "interrupted"
                    job.error_message = "Core stopped while this job was running and no attempts are left. Retry it."
                    add_log(s, self.ctx, job.id, job.error_message, "error")
        if n:
            log.info("jobs_recovered", count=n)
        return n

    # ---------- cancellation ----------
    def cancel_event(self, job_id: str) -> threading.Event:
        with self._cancel_lock:
            return self._cancel.setdefault(job_id, threading.Event())

    def signal_cancel(self, job_id: str) -> None:
        with self._cancel_lock:
            ev = self._cancel.get(job_id)
        if ev is not None:
            ev.set()

    # ---------- work ----------
    def claim(self) -> str | None:
        ctx = self.ctx
        with ctx.db.tx() as s:
            now = ctx.clock.iso()
            job = s.scalars(
                select(Job)
                .where(Job.status == "queued", Job.run_after <= now)
                .order_by(Job.created_at, Job.id)
                .limit(1)
            ).first()
            if job is None:
                return None
            job.status = "running"
            job.stage = "preparing"
            job.attempt += 1
            job.lease_owner = self.owner
            job.lease_expires_at = to_iso(ctx.clock.now() + timedelta(seconds=LEASE_SECONDS))
            job.started_at = job.started_at or now
            job.error_code = None
            job.error_message = None
            add_log(s, ctx, job.id, f"Attempt {job.attempt} of {job.max_attempts} started.")
            return job.id

    def run_once(self) -> bool:
        """Claim and run one job synchronously (used by tests and the CLI)."""
        job_id = self.claim()
        if job_id is None:
            return False
        self._execute(job_id)
        return True

    def run_until_idle(self, limit: int = 50) -> int:
        n = 0
        while n < limit and self.run_once():
            n += 1
        return n

    def _execute(self, job_id: str) -> None:
        from pbs_core.jobs.execute import run_job

        ev = self.cancel_event(job_id)
        try:
            run_job(self.ctx, job_id, ev, self._ollama)
        finally:
            with self._cancel_lock:
                self._cancel.pop(job_id, None)
            self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self._workers.acquire(timeout=self.poll_seconds):
                continue
            try:
                job_id = self.claim()
            except Exception:  # database busy etc. - try again shortly
                log.exception("job_claim_failed")
                job_id = None
            if job_id is None:
                self._workers.release()
                self._wake.wait(self.poll_seconds)
                self._wake.clear()
                continue

            def work(jid: str = job_id) -> None:
                try:
                    self._execute(jid)
                except Exception:
                    log.exception("job_worker_crashed", job_id=jid)
                finally:
                    self._workers.release()

            self._pool.submit(work)
