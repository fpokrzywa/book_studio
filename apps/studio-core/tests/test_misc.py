"""System endpoints, capability report, backup manifest structure, OpenAPI contract."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from pbs_core.openapi_export import openapi_json
from pbs_core.storage.backup_manifest import BackupManifest, ManifestFile

REPO = Path(__file__).resolve().parents[3]
CONTRACT = REPO / "apps" / "studio-ui" / "src" / "api" / "openapi.json"


def test_system_info(client: TestClient) -> None:
    info = client.get("/api/system/info").json()
    assert info["privacy_mode"] == "local_only"
    assert info["schema_revision"] == "0003"
    assert info["env"] == "test"


def test_capabilities_report(client: TestClient) -> None:
    caps = client.get("/api/system/capabilities").json()
    ids = {c["id"] for c in caps}
    assert {"pandoc", "java", "ollama", "weasyprint", "ebook-convert"} <= ids
    assert all(isinstance(c["found"], bool) for c in caps)


def test_backup_manifest_valid() -> None:
    m = BackupManifest(
        app_version="0.1.0",
        schema_revision="0002",
        created_at="2026-11-22T00:00:00.000Z",
        project_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        project_title="Book",
        tables={"project": 1},
        files=[ManifestFile(path="data/project.jsonl", sha256="a" * 64, byte_size=10)],
    )
    assert m.model_dump(by_alias=True)["schema"] == "manifest/1"


@pytest.mark.parametrize("path", ["../evil", "/abs", "data/../../x", "data\\x", "other/x", "files/CON", "files/a:b"])
def test_backup_manifest_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        ManifestFile(path=path, sha256="a" * 64, byte_size=1)


def test_openapi_contract_is_current() -> None:
    """The committed contract (used to generate the TS client) must match the code."""
    assert CONTRACT.exists(), "run scripts/gen-api to create the API contract"
    assert CONTRACT.read_text(encoding="utf-8") == openapi_json(), "API contract is stale: run scripts/gen-api"
