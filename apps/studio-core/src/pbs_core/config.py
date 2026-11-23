"""Runtime configuration (environment variables prefixed with PBS_).

Two deployments:

* ``local`` (default): one person on one computer. Core listens on loopback only.
* ``server``: self-hosted on a Linux server behind an HTTPS reverse proxy (docs/DEPLOYMENT.md).
  Core may listen on a container interface, but only the proxy can reach it; ``PBS_PUBLIC_ORIGIN``
  names the one https address browsers use, and every request is checked against it.

Both deployments require a signed-in account for every /api request (docs/SECURITY.md section 2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from platformdirs import user_documents_dir
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class ConfigError(RuntimeError):
    """Raised when configuration is unsafe or invalid."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PBS_", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    deployment: Literal["local", "server"] = "local"
    role: Literal["all", "web", "worker"] = "all"  # web + worker in one process, or split (server)
    workspace: Path | None = None
    host: str = "127.0.0.1"
    port: int = 8765
    public_origin: str | None = None  # server: https://books.example.lan (no path)
    trusted_proxies: list[str] = []  # server: the reverse proxy's address (X-Forwarded-* is trusted from it)
    ui_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]
    ui_dist: Path | None = None  # built UI (apps/studio-ui/dist) served by Core itself
    log_level: str = "INFO"
    log_console: bool = True
    max_upload_mb: int = 200
    max_backup_mb: int = 4096
    secret_backend: Literal["auto", "encrypted-file", "keyring", "dev-file", "memory"] = "auto"  # noqa: S105
    secret_key_file: Path | None = None  # 32-byte key for encrypted-file (a Docker secret, outside the data volume)
    local_ai_hosts: list[str] = []  # operator-named private model hosts treated as local (e.g. ["ollama"])
    allow_cloud: bool = True  # operator switch: false forces local-only whatever the in-app setting says
    session_idle_minutes: int = 12 * 60
    session_max_days: int = 14
    ai_workers: int = 2
    ai_runner: bool = True  # tests drive the runner by hand

    @field_validator("port")
    @classmethod
    def _port_range(cls, value: int) -> int:
        if not (0 <= value <= 65535):
            raise ValueError("PBS_PORT must be between 0 and 65535")
        return value

    @field_validator("local_ai_hosts")
    @classmethod
    def _plain_hosts(cls, value: list[str]) -> list[str]:
        out = []
        for h in value:
            h = h.strip().lower()
            if not h or any(c in h for c in "/:@ ") or h in ("*", "0.0.0.0"):  # noqa: S104 - rejected, not bound
                raise ValueError(f"PBS_LOCAL_AI_HOSTS entries must be plain host names (got {h!r}).")
            out.append(h)
        return out

    @model_validator(mode="after")
    def _deployment_rules(self) -> Settings:
        if self.deployment == "local":
            if self.host not in LOOPBACK_HOSTS:
                raise ValueError(
                    f"PBS_HOST must be a loopback address ({', '.join(sorted(LOOPBACK_HOSTS))}); got {self.host!r}. "
                    "A local deployment never listens on external interfaces; use PBS_DEPLOYMENT=server behind "
                    "an HTTPS reverse proxy instead."
                )
            return self
        if not self.public_origin:
            raise ValueError("PBS_DEPLOYMENT=server needs PBS_PUBLIC_ORIGIN, e.g. https://books.example.lan")
        parts = urlsplit(self.public_origin)
        if parts.scheme not in ("https", "http") or not parts.hostname or parts.path not in ("", "/"):
            raise ValueError("PBS_PUBLIC_ORIGIN must be an origin such as https://books.example.lan (no path).")
        if parts.scheme != "https" and self.env != "test":
            raise ValueError("PBS_PUBLIC_ORIGIN must use https: browsers reach the studio only over HTTPS.")
        self.public_origin = f"{parts.scheme}://{parts.netloc.lower()}"
        return self

    # ---------- derived ----------
    @property
    def runs_jobs(self) -> bool:
        """Whether this process runs the background job and task runner."""
        return self.role in ("all", "worker") and self.ai_runner

    @property
    def serves_http(self) -> bool:
        return self.role in ("all", "web")

    @property
    def cookie_secure(self) -> bool:
        return bool(self.public_origin and self.public_origin.startswith("https://"))

    def resolved_workspace(self) -> Path:
        """Workspace root. Explicit PBS_WORKSPACE wins; otherwise dev uses ./.pbs-data."""
        if self.workspace is not None:
            return self.workspace.expanduser().resolve()
        if self.deployment == "server":
            return Path("/data").resolve()
        if self.env == "prod":
            return (Path(user_documents_dir()) / "Personal Book Studio").resolve()
        return (Path.cwd() / ".pbs-data").resolve()

    def allowed_hosts(self) -> frozenset[str]:
        """Host headers Core answers to. Loopback stays allowed for in-container health checks."""
        port = self.port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
        if self.public_origin:
            parts = urlsplit(self.public_origin)
            hosts.add(parts.netloc.lower())
            default_port = 443 if parts.scheme == "https" else 80
            if parts.port in (None, default_port) and parts.hostname:
                hosts.add(parts.hostname.lower())
                hosts.add(f"{parts.hostname.lower()}:{default_port}")
        return frozenset(hosts)

    def allowed_origins(self) -> frozenset[str]:
        if self.deployment == "server" and self.public_origin:
            return frozenset({self.public_origin})  # the development UI origins never apply to a server
        return frozenset(self.ui_origins)
