"""Provider credentials. Never stored in the database, logs, exports or backups.

Backends, in order of preference:

* ``keyring``: the operating system credential store (Windows Credential Manager, macOS
  Keychain, Secret Service on Linux). The default whenever a secure backend is available.
* ``env``: read-only, ``PBS_<KIND>_API_KEY`` environment variables (e.g. PBS_OPENAI_API_KEY).
  Nothing is written anywhere; the UI shows an "insecure key source" warning.
* ``dev-file``: explicit opt-in for development machines without a credential store
  (``PBS_SECRET_BACKEND=dev-file``). A JSON file in ``<workspace>/runtime/`` restricted to the
  current user. Clearly labelled as a weaker fallback; ``runtime/`` is never exported or backed up.
* ``memory``: tests only.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from pathlib import Path
from typing import Protocol

import structlog

from pbs_core.security.token import restrict_directory
from pbs_core.storage.paths import atomic_write_bytes

log = structlog.get_logger(__name__)
SERVICE = "PersonalBookStudio"


class SecretStoreError(RuntimeError):
    pass


class SecretStore(Protocol):
    name: str
    secure: bool
    writable: bool

    def get(self, ref: str) -> str | None: ...
    def set(self, ref: str, value: str) -> None: ...
    def delete(self, ref: str) -> None: ...


class KeyringStore:
    name = "keyring"
    secure = True
    writable = True

    def __init__(self) -> None:
        import keyring

        self._keyring = keyring
        self.backend_label = type(keyring.get_keyring()).__name__

    def get(self, ref: str) -> str | None:
        value: str | None = self._keyring.get_password(SERVICE, ref)
        return value

    def set(self, ref: str, value: str) -> None:
        self._keyring.set_password(SERVICE, ref, value)

    def delete(self, ref: str) -> None:
        # keyring raises PasswordDeleteError when the entry is already gone: that is the goal.
        with contextlib.suppress(Exception):
            self._keyring.delete_password(SERVICE, ref)


class MemoryStore:
    name = "memory"
    secure = False
    writable = True

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, ref: str) -> str | None:
        return self._data.get(ref)

    def set(self, ref: str, value: str) -> None:
        self._data[ref] = value

    def delete(self, ref: str) -> None:
        self._data.pop(ref, None)


class DevFileStore:
    name = "dev-file"
    secure = False
    writable = True

    def __init__(self, runtime_dir: Path) -> None:
        self.path = runtime_dir / "dev-secrets.json"
        self._lock = threading.Lock()
        if not restrict_directory(runtime_dir):
            log.warning("dev_secret_store_acl_not_restricted", path=str(runtime_dir))
        log.warning("insecure_secret_backend", backend="dev-file", detail="keys are protected only by file permissions")

    def _read(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return {str(k): str(v) for k, v in data.items()}
        except FileNotFoundError:
            return {}

    def get(self, ref: str) -> str | None:
        with self._lock:
            return self._read().get(ref)

    def set(self, ref: str, value: str) -> None:
        with self._lock:
            data = self._read()
            data[ref] = value
            atomic_write_bytes(self.path, json.dumps(data).encode("utf-8"))
            if os.name != "nt":
                os.chmod(self.path, 0o600)

    def delete(self, ref: str) -> None:
        with self._lock:
            data = self._read()
            if data.pop(ref, None) is not None:
                atomic_write_bytes(self.path, json.dumps(data).encode("utf-8"))


class ReadOnlyStore:
    """No writable backend available: keys can only come from environment variables."""

    name = "none"
    secure = False
    writable = False

    def get(self, ref: str) -> str | None:
        return None

    def set(self, ref: str, value: str) -> None:
        raise SecretStoreError(
            "No secure credential store is available. Set PBS_<PROVIDER>_API_KEY environment variables, "
            "or explicitly enable the development file store (PBS_SECRET_BACKEND=dev-file)."
        )

    def delete(self, ref: str) -> None:
        return None


def build_store(backend: str, runtime_dir: Path) -> SecretStore:
    if backend == "memory":
        return MemoryStore()
    if backend == "dev-file":
        return DevFileStore(runtime_dir)
    if backend in ("auto", "keyring"):
        try:
            import keyring
            from keyring.backends import fail

            if not isinstance(keyring.get_keyring(), fail.Keyring):
                return KeyringStore()
        except Exception as exc:
            log.warning("keyring_unavailable", error_type=type(exc).__name__)
        if backend == "keyring":
            raise SecretStoreError("The OS credential store is not available on this machine.")
    return ReadOnlyStore()


def env_key(kind: str) -> str | None:
    value = os.environ.get(f"PBS_{kind.upper()}_API_KEY")
    return value.strip() if value and value.strip() else None


def credential_ref(provider_id: str) -> str:
    return f"provider:{provider_id}"
