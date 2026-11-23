"""Application context: settings, workspace, database, IDs, clock and secret store."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from pbs_core import __version__
from pbs_core.config import Settings
from pbs_core.domain.clock import Clock
from pbs_core.domain.ids import UlidFactory
from pbs_core.logging_setup import close_logging, configure_logging
from pbs_core.providers import egress
from pbs_core.security.fs import restrict_directory
from pbs_core.security.secrets import ReadOnlyStore, SecretStore, build_store
from pbs_core.storage.db import Database, create_sqlite_engine
from pbs_core.storage.migrate import MigrationResult, migrate
from pbs_core.storage.models import AppSetting
from pbs_core.storage.paths import Workspace

if TYPE_CHECKING:
    from pbs_core.jobs.runner import JobRunner

log = structlog.get_logger(__name__)

DEFAULT_SETTINGS = {"privacy_mode": "local_only"}


@dataclass
class AppContext:
    settings: Settings
    workspace: Workspace
    db: Database
    ids: UlidFactory
    clock: Clock
    migration: MigrationResult
    secrets: SecretStore = field(default=None)  # type: ignore[assignment]  # set by build_context
    http_transport: Any = None  # tests inject an httpx2.MockTransport; None = real network (gated)
    jobs: JobRunner | None = None

    @property
    def schema_revision(self) -> str:
        return self.migration.to_revision

    def setting(self, key: str) -> object:
        with self.db.tx() as s:
            row = s.get(AppSetting, key)
            return json.loads(row.value_json) if row else DEFAULT_SETTINGS.get(key)

    def close(self) -> None:
        self.db.dispose()
        close_logging()


def build_context(
    settings: Settings,
    *,
    clock: Clock | None = None,
    ids: UlidFactory | None = None,
    secrets: SecretStore | None = None,
) -> AppContext:
    workspace = Workspace(settings.resolved_workspace())
    workspace.ensure()
    configure_logging(workspace.logs_dir, settings.log_level, console=settings.log_console)
    clock = clock or Clock()
    engine = create_sqlite_engine(workspace.db_path)
    result = migrate(engine, workspace.db_path, workspace.db_backups_dir, clock.iso())
    if result.migrated:
        log.info(
            "schema_migrated",
            from_revision=result.from_revision,
            to_revision=result.to_revision,
            snapshot=str(result.snapshot_path) if result.snapshot_path else None,
        )
    db = Database(engine)
    with db.tx() as s:
        for key, value in DEFAULT_SETTINGS.items():
            if s.get(AppSetting, key) is None:
                s.add(AppSetting(key=key, value_json=json.dumps(value)))
    if not restrict_directory(workspace.runtime_dir):
        log.warning("runtime_dir_acl_not_restricted", path=str(workspace.runtime_dir))
    workspace.legacy_token_path.unlink(missing_ok=True)
    egress.configure_local_hosts(settings.local_ai_hosts)
    log.info(
        "core_ready",
        version=__version__,
        workspace=str(workspace.root),
        schema=result.to_revision,
        deployment=settings.deployment,
        role=settings.role,
    )
    if (
        secrets is None
        and settings.deployment == "server"
        and settings.secret_backend == "auto"  # noqa: S105 - a backend name
        and settings.secret_key_file is None
    ):
        secrets = ReadOnlyStore()  # no desktop keyring on a headless server: env keys only, said in the UI
    store = secrets or build_store(settings.secret_backend, workspace.runtime_dir, settings.secret_key_file)
    log.info("secret_store", backend=store.name, secure=store.secure, writable=store.writable)
    return AppContext(settings, workspace, db, ids or UlidFactory(), clock, result, secrets=store)
