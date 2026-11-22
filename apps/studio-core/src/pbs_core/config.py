"""Runtime configuration (environment variables prefixed with PBS_)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from platformdirs import user_documents_dir
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class ConfigError(RuntimeError):
    """Raised when configuration is unsafe or invalid."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PBS_", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    workspace: Path | None = None
    host: str = "127.0.0.1"
    port: int = 8765
    ui_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]
    log_level: str = "INFO"
    log_console: bool = True
    max_upload_mb: int = 200
    max_backup_mb: int = 4096

    @field_validator("host")
    @classmethod
    def _loopback_only(cls, value: str) -> str:
        if value not in LOOPBACK_HOSTS:
            raise ValueError(
                f"PBS_HOST must be a loopback address ({', '.join(sorted(LOOPBACK_HOSTS))}); "
                f"got {value!r}. Personal Book Studio never listens on external interfaces."
            )
        return value

    @field_validator("port")
    @classmethod
    def _port_range(cls, value: int) -> int:
        if not (0 <= value <= 65535):
            raise ValueError("PBS_PORT must be between 0 and 65535")
        return value

    def resolved_workspace(self) -> Path:
        """Workspace root. Explicit PBS_WORKSPACE wins; otherwise dev uses ./.pbs-data."""
        if self.workspace is not None:
            return self.workspace.expanduser().resolve()
        if self.env == "prod":
            return (Path(user_documents_dir()) / "Personal Book Studio").resolve()
        return (Path.cwd() / ".pbs-data").resolve()

    def allowed_hosts(self) -> frozenset[str]:
        port = self.port
        return frozenset({f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"})
