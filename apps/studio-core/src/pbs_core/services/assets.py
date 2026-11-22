"""Project assets (images). Content-addressed; referenced from text as ``asset:<16-hex short hash>``.

Only raster formats recognised by their magic bytes are accepted (PNG, JPEG, GIF, WebP).
SVG is refused: it can carry scripts.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.contracts import AssetOut
from pbs_core.domain.errors import NotFoundError, ValidationFailedError
from pbs_core.services.projects import require_active, require_project
from pbs_core.storage.models import Asset
from pbs_core.storage.paths import atomic_write_bytes, safe_join

MAX_ASSET_BYTES = 25 * 1024 * 1024
_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}


def sniff_image(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def image_size(data: bytes, mime: str) -> tuple[int | None, int | None]:
    try:
        if mime == "image/png" and len(data) >= 24:
            w, h = struct.unpack(">II", data[16:24])
            return int(w), int(h)
        if mime == "image/gif" and len(data) >= 10:
            w, h = struct.unpack("<HH", data[6:10])
            return int(w), int(h)
        if mime == "image/jpeg":
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    break
                marker = data[i + 1]
                seg_len = struct.unpack(">H", data[i + 2 : i + 4])[0]
                if marker in (0xC0, 0xC1, 0xC2):
                    h, w = struct.unpack(">HH", data[i + 5 : i + 9])
                    return int(w), int(h)
                i += 2 + seg_len
    except struct.error:
        pass
    return None, None


def store(
    s: Session,
    ctx: AppContext,
    project_id: str,
    data: bytes,
    *,
    original_name: str | None,
    import_run_id: str | None = None,
) -> Asset:
    """Store image bytes for a project (deduplicated by SHA-256). Caller owns the transaction."""
    if len(data) > MAX_ASSET_BYTES:
        raise ValidationFailedError(f"Images must be under {MAX_ASSET_BYTES // (1024 * 1024)} MB.")
    mime = sniff_image(data)
    if mime is None:
        raise ValidationFailedError("Only PNG, JPEG, GIF and WebP images are supported.")
    digest = hashlib.sha256(data).hexdigest()
    existing = s.scalars(select(Asset).where(Asset.project_id == project_id, Asset.sha256 == digest)).one_or_none()
    if existing is not None:
        return existing
    rel = f"assets/sha256/{digest[:2]}/{digest}.{_EXT[mime]}"
    target = safe_join(ctx.workspace.project_dir(project_id), rel)
    if not target.exists():
        atomic_write_bytes(target, data)
    w, h = image_size(data, mime)
    asset = Asset(
        id=ctx.ids.new(),
        project_id=project_id,
        sha256=digest,
        short_hash=digest[:16],
        mime=mime,
        byte_size=len(data),
        width_px=w,
        height_px=h,
        original_name=(original_name or None) and original_name[:255],
        storage_path=rel,
        import_run_id=import_run_id,
        created_at=ctx.clock.iso(),
    )
    s.add(asset)
    s.flush()
    return asset


def to_out(a: Asset) -> AssetOut:
    return AssetOut(
        id=a.id,
        short_hash=a.short_hash,
        mime=a.mime,
        byte_size=a.byte_size,
        width_px=a.width_px,
        height_px=a.height_px,
        original_name=a.original_name,
        reference=f"asset:{a.short_hash}",
        url=f"/api/projects/{a.project_id}/assets/{a.short_hash}",
        created_at=a.created_at,
    )


def upload(ctx: AppContext, project_id: str, data: bytes, name: str | None) -> AssetOut:
    with ctx.db.tx() as s:
        require_active(s, project_id)
        return to_out(store(s, ctx, project_id, data, original_name=name))


def list_assets(ctx: AppContext, project_id: str) -> list[AssetOut]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        rows = s.scalars(select(Asset).where(Asset.project_id == project_id).order_by(Asset.created_at)).all()
        return [to_out(a) for a in rows]


def asset_file(ctx: AppContext, project_id: str, short_hash: str) -> tuple[Path, str]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        asset = s.scalars(
            select(Asset).where(Asset.project_id == project_id, Asset.short_hash == short_hash)
        ).one_or_none()
        if asset is None:
            raise NotFoundError("Image not found in this project.")
        path = safe_join(ctx.workspace.project_dir(project_id), asset.storage_path)
        if not path.is_file():
            raise NotFoundError("The image file is missing from disk.")
        return path, asset.mime
