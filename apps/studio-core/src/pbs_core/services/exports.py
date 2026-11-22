"""Exports: Markdown (`pbs-md-export/1`, bundled with images as a ZIP when needed) and standalone HTML.

Every format is built from the same canonical chapter order and the head revision of each chapter.
Markdown keeps each chapter's text verbatim. HTML is rendered from the canonical document model by
the same renderer as the editor preview.
"""

from __future__ import annotations

import base64
import hashlib
import html as html_lib
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.contracts import ExportOut
from pbs_core.document import bookmd
from pbs_core.document import html as html_render
from pbs_core.domain.errors import NotFoundError
from pbs_core.domain.ids import is_ulid
from pbs_core.services import activity, documents
from pbs_core.services.chapters import active_chapters, tree_order
from pbs_core.services.projects import require_project
from pbs_core.storage.models import Asset, Chapter, ChapterRevision, ExportRun, Project
from pbs_core.storage.paths import atomic_write_bytes, safe_join, sanitize_filename

EXPORT_SCHEMA = "pbs-md-export/1"
_ASSET_LINK = re.compile(r"\(asset:([0-9a-f]{16})")
_FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)

Entry = tuple[Chapter, ChapterRevision | None, int]


def _q(value: str) -> str:
    """YAML double-quoted scalar (JSON string syntax is valid YAML)."""
    return json.dumps(value, ensure_ascii=False)


def _ordered(s: Session, project_id: str) -> list[Entry]:
    out: list[Entry] = []
    for chapter, depth in tree_order(active_chapters(s, project_id)):
        head = (
            s.scalars(
                select(ChapterRevision).where(
                    ChapterRevision.project_id == project_id, ChapterRevision.id == chapter.head_revision_id
                )
            ).one_or_none()
            if chapter.head_revision_id
            else None
        )
        out.append((chapter, head, depth))
    return out


def render_markdown(project: Project, export_id: str, entries: list[Entry]) -> tuple[str, list[str]]:
    warnings: list[str] = []
    lines = ["---", f"title: {_q(project.title)}"]
    if project.subtitle:
        lines.append(f"subtitle: {_q(project.subtitle)}")
    if project.author_name:
        lines.append(f"author: {_q(project.author_name)}")
    if project.description:
        lines.append(f"description: {_q(project.description)}")
    lines += [
        f"lang: {_q(project.language)}",
        "pbs_export:",
        f"  schema: {_q(EXPORT_SCHEMA)}",
        f"  project_id: {_q(project.id)}",
        f"  export_id: {_q(export_id)}",
        "---",
        "",
    ]
    parts: list[str] = ["\n".join(lines)]
    for chapter, head, depth in entries:
        section = f"{'#' * min(depth + 1, 6)} {chapter.title} {{#ch-{chapter.slug}}}\n\n"
        if head is None or not head.source_md.strip():
            warnings.append(f"Chapter “{chapter.title}” has no saved content; exported as a heading only.")
        else:
            section += head.source_md if head.source_md.endswith("\n") else head.source_md + "\n"
        parts.append(section)
    if not entries:
        warnings.append("The project has no chapters; the export contains metadata only.")
    return "\n".join(parts), warnings


def _assets(s: Session, project_id: str) -> dict[str, Asset]:
    return {a.short_hash: a for a in s.scalars(select(Asset).where(Asset.project_id == project_id)).all()}


def _asset_bytes(ctx: AppContext, asset: Asset) -> bytes:
    return safe_join(ctx.workspace.project_dir(asset.project_id), asset.storage_path).read_bytes()


def _zip_bytes(files: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in sorted(files):
            info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return buf.getvalue()


def _build_markdown(ctx: AppContext, s: Session, project: Project, export_id: str) -> tuple[str, bytes, str, list[str]]:
    entries = _ordered(s, project.id)
    text, warnings = render_markdown(project, export_id, entries)
    refs = sorted(set(_ASSET_LINK.findall(text)))
    base = sanitize_filename(project.title)
    if not refs:
        return "markdown", text.encode("utf-8"), f"{base}.md", warnings
    assets = _assets(s, project.id)
    files: list[tuple[str, bytes]] = []
    for ref in refs:
        asset = assets.get(ref)
        if asset is None:
            warnings.append(f"Image asset:{ref} is referenced but missing from the project; its link is kept as-is.")
            continue
        ext = asset.storage_path.rsplit(".", 1)[-1]
        files.append((f"assets/{ref}.{ext}", _asset_bytes(ctx, asset)))
        text = text.replace(f"(asset:{ref}", f"(assets/{ref}.{ext}")
    files.append((f"{base}.md", text.encode("utf-8")))
    warnings.append("Images are included in the assets/ folder of this ZIP; the Markdown links point to them.")
    return "markdown_zip", _zip_bytes(files), f"{base}.zip", warnings


_HTML_STYLE = """
body{font-family:Georgia,serif;line-height:1.6;max-width:42rem;margin:2rem auto;padding:0 1rem;color:#1d2a33}
h1,h2,h3{line-height:1.2}figure{margin:1.5rem 0}img{max-width:100%;height:auto}
figcaption,caption{font-size:.9em;color:#4f5d66}table{border-collapse:collapse}
th,td{border:1px solid #c9d1cd;padding:.3rem .6rem}pre{overflow:auto;background:#eef1ef;padding:.75rem}
.align-right{text-align:right}.align-center{text-align:center}.footnotes{font-size:.9em}
.external-image,.missing-image,.unsafe-link{color:#9b2c2c}
"""


def _build_html(ctx: AppContext, s: Session, project: Project) -> tuple[str, bytes, str, list[str]]:
    entries = _ordered(s, project.id)
    assets = _assets(s, project.id)
    warnings: list[str] = []
    uris: dict[str, str] = {}

    def resolve(h: str) -> str | None:
        asset = assets.get(h)
        if asset is None:
            return None
        if h not in uris:
            uris[h] = f"data:{asset.mime};base64," + base64.b64encode(_asset_bytes(ctx, asset)).decode("ascii")
        return uris[h]

    toc: list[str] = []
    sections: list[str] = []
    for chapter, head, depth in entries:
        level = min(depth + 1, 6)
        anchor = f"ch-{chapter.slug}"
        toc.append(f'<li class="toc-{depth}"><a href="#{anchor}">{html_lib.escape(chapter.title)}</a></li>')
        body = ""
        if head is not None:
            doc: dict[str, Any] = documents.bdm_of(ctx, head)
            rendered = html_render.render(doc, resolve, allow_data_urls=True, id_prefix=f"{chapter.slug}-")
            body = rendered.html
            warnings.extend(f"{chapter.title}: {w['message']}" for w in rendered.warnings)
            warnings.extend(
                f"{chapter.title}: {w.message}"
                for w in bookmd.parse(head.source_md, chapter_id=chapter.id, new_id=ctx.ids.new).warnings
                if w.code in ("external_image", "unresolved_image", "unsupported_block")
            )
        else:
            warnings.append(f"Chapter “{chapter.title}” has no saved content; exported as a heading only.")
        sections.append(
            f'<section id="{anchor}"><h{level} class="chapter-title">{html_lib.escape(chapter.title)}</h{level}>'
            f"{body}</section>"
        )
    meta = [f'<h1 class="book-title">{html_lib.escape(project.title)}</h1>']
    if project.subtitle:
        meta.append(f'<p class="subtitle">{html_lib.escape(project.subtitle)}</p>')
    if project.author_name:
        meta.append(f'<p class="author">{html_lib.escape(project.author_name)}</p>')
    csp = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"
    doc_html = (
        "<!doctype html>\n"
        f'<html lang="{html_lib.escape(project.language)}">\n<head>\n<meta charset="utf-8">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{csp}">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<meta name="generator" content="Personal Book Studio ({EXPORT_SCHEMA.replace("md", "html")})">\n'
        f"<title>{html_lib.escape(project.title)}</title>\n<style>{_HTML_STYLE}</style>\n</head>\n<body>\n"
        f"<header>{''.join(meta)}</header>\n"
        f'<nav aria-label="Contents"><ol>{"".join(toc)}</ol></nav>\n'
        f"<main>{''.join(sections)}</main>\n</body>\n</html>\n"
    )
    return "html", doc_html.encode("utf-8"), f"{sanitize_filename(project.title)}.html", warnings


def _out(run: ExportRun) -> ExportOut:
    revision_set = json.loads(run.revision_set_json)
    return ExportOut(
        id=run.id,
        project_id=run.project_id,
        format=run.format,
        status=run.status,
        file_name=run.file_name,
        sha256=run.sha256,
        byte_size=run.byte_size,
        chapter_count=len(revision_set),
        warnings=json.loads(run.warnings_json),
        started_at=run.started_at,
        finished_at=run.finished_at,
        download_url=(f"/api/projects/{run.project_id}/exports/{run.id}/file" if run.status == "completed" else None),
    )


def export_project(ctx: AppContext, project_id: str, fmt: str = "markdown") -> ExportOut:
    started = ctx.clock.iso()
    export_id = ctx.ids.new()
    with ctx.db.tx() as s:
        project = require_project(s, project_id)
        entries = _ordered(s, project_id)
        if fmt == "html":
            kind, data, file_name, warnings = _build_html(ctx, s, project)
        else:
            kind, data, file_name, warnings = _build_markdown(ctx, s, project, export_id)
        rel = f"exports/{export_id}/{file_name}"
        atomic_write_bytes(safe_join(ctx.workspace.project_dir(project_id), rel), data)
        run = ExportRun(
            id=export_id,
            project_id=project_id,
            format=kind,
            revision_set_json=json.dumps({c.id: (r.id if r else None) for c, r, _ in entries}),
            status="completed",
            output_path=rel,
            file_name=file_name,
            sha256=hashlib.sha256(data).hexdigest(),
            byte_size=len(data),
            warnings_json=json.dumps(warnings, ensure_ascii=False),
            started_at=started,
            finished_at=ctx.clock.iso(),
        )
        s.add(run)
        label = {"markdown": "Markdown", "markdown_zip": "Markdown with images", "html": "HTML"}[kind]
        activity.record(s, ctx, kind="export_completed", summary=f"Exported “{project.title}” as {label}",
                        project_id=project_id, ref_type="export_run", ref_id=export_id)  # fmt: skip
        s.flush()
        return _out(run)


def export_markdown(ctx: AppContext, project_id: str) -> ExportOut:
    return export_project(ctx, project_id, "markdown")


def list_exports(ctx: AppContext, project_id: str) -> list[ExportOut]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        runs = s.scalars(
            select(ExportRun).where(ExportRun.project_id == project_id).order_by(ExportRun.started_at.desc()).limit(20)
        ).all()
        return [_out(r) for r in runs]


MEDIA_TYPES = {
    "markdown": "text/markdown; charset=utf-8",
    "markdown_zip": "application/zip",
    "html": "text/html; charset=utf-8",
}


def export_file(ctx: AppContext, project_id: str, export_id: str) -> tuple[Path, str, str]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        run = (
            s.scalars(
                select(ExportRun).where(ExportRun.project_id == project_id, ExportRun.id == export_id)
            ).one_or_none()
            if is_ulid(export_id)
            else None
        )
        if run is None or run.output_path is None or run.file_name is None:
            raise NotFoundError("Export not found.")
        path = safe_join(ctx.workspace.project_dir(project_id), run.output_path)
        if not path.is_file():
            raise NotFoundError("The export file is missing from disk.")
        return path, run.file_name, MEDIA_TYPES.get(run.format, "application/octet-stream")
