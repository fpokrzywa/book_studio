"""Application context: settings, workspace, database, IDs, clock and session token."""

from __future__ import annotations

import json
from dataclasses import dataclass

import structlog

from pbs_core import __version__
from pbs_core.config import Settings
from pbs_core.domain.clock import Clock
from pbs_core.domain.ids import UlidFactory
from pbs_core.logging_setup import close_logging, configure_logging
from pbs_core.security.token import generate_token, write_token
from pbs_core.storage.db import Database, create_sqlite_engine
from pbs_core.storage.migrate import MigrationResult, migrate
from pbs_core.storage.models import AppSetting
from pbs_core.storage.paths import Workspace

log = structlog.get_logger(__name__)

DEFAULT_SETTINGS = {"privacy_mode": "local_only"}


@dataclass
class AppContext:
    settings: Settings
    workspace: Workspace
    db: Database
    ids: UlidFactory
    clock: Clock
    token: str
    migration: MigrationResult

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


def build_context(settings: Settings, *, clock: Clock | None = None, ids: UlidFactory | None = None) -> AppContext:
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
    token = generate_token()
    write_token(workspace.runtime_dir, workspace.token_path, token)
    log.info("core_ready", version=__version__, workspace=str(workspace.root), schema=result.to_revision)
    return AppContext(settings, workspace, db, ids or UlidFactory(), clock, token, result)
