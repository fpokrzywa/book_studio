"""Knowledge libraries and sources: import, deduplicate, index, search, view, remove, cite.

Rules (docs/SECURITY.md §5, ADR-0005):
* The original upload is kept byte-for-byte (shared `original_file` store); chunks are derived.
* A source is used by AI only while it is enabled, indexed and not removed, and only for books
  that own its library or opted in to it (shared libraries).
* Titles come from the file's metadata or its name until the author changes them; authors, year,
  publisher, URL and DOI are only ever what the author typed. Citation keys never change.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.contracts import WarningOut
from pbs_core.contracts_knowledge import (
    BookKnowledgeOut,
    ChunkOut,
    CitationOut,
    DuplicateOut,
    LibraryCreate,
    LibraryOut,
    LibraryPatch,
    SearchHitOut,
    SearchOut,
    SnippetPart,
    SourceImportOut,
    SourceOut,
    SourcePatch,
    SourceTextOut,
)
from pbs_core.domain.errors import ConflictError, NotFoundError, ValidationFailedError
from pbs_core.domain.ids import is_ulid
from pbs_core.importers import detect_format
from pbs_core.importers.base import ImportError_
from pbs_core.knowledge import extract as ex
from pbs_core.knowledge import retrieval, search
from pbs_core.services import activity
from pbs_core.services.imports import _read_original, _store_original
from pbs_core.services.projects import require_active, require_project
from pbs_core.storage.knowledge_models import ClaimSupport, KnowledgeLibrary, LibraryLink, Source, SourceChunk
from pbs_core.storage.models import Chapter, ChapterRevision, OriginalFile

SEMANTIC_NOTE = (
    "Meaning-based (semantic) search needs a local embedding model and is not available yet. "
    "Results come from word matching (SQLite FTS5)."
)
_CITE_KEY = re.compile(r"@([A-Za-z0-9_][\w:.#$%&+?<>~/-]*)")


# ---------- libraries ----------


def _library_out(s: Session, lib: KnowledgeLibrary) -> LibraryOut:
    count = s.scalar(
        select(func.count()).select_from(Source).where(Source.library_id == lib.id, Source.removed_at.is_(None))
    )
    links = s.scalars(select(LibraryLink.project_id).where(LibraryLink.library_id == lib.id)).all()
    return LibraryOut(
        id=lib.id,
        name=lib.name,
        scope=lib.scope,
        project_id=lib.project_id,
        description=lib.description,
        source_count=int(count or 0),
        linked_project_ids=list(links),
        created_at=lib.created_at,
    )


def _require_library(s: Session, library_id: str) -> KnowledgeLibrary:
    lib = s.get(KnowledgeLibrary, library_id) if is_ulid(library_id) else None
    if lib is None or lib.archived_at is not None:
        raise NotFoundError("Knowledge library not found.")
    return lib


def ensure_project_library(s: Session, ctx: AppContext, project_id: str) -> KnowledgeLibrary:
    lib = s.scalars(
        select(KnowledgeLibrary).where(
            KnowledgeLibrary.scope == "project",
            KnowledgeLibrary.project_id == project_id,
            KnowledgeLibrary.archived_at.is_(None),
        )
    ).first()
    if lib is None:
        project = require_project(s, project_id)
        now = ctx.clock.iso()
        lib = KnowledgeLibrary(
            id=ctx.ids.new(),
            name=f"Sources for {project.title}"[:120],
            scope="project",
            project_id=project_id,
            description=None,
            created_at=now,
            updated_at=now,
        )
        s.add(lib)
        s.flush()
    return lib


def list_shared(ctx: AppContext) -> list[LibraryOut]:
    with ctx.db.tx() as s:
        libs = s.scalars(
            select(KnowledgeLibrary)
            .where(KnowledgeLibrary.scope == "shared", KnowledgeLibrary.archived_at.is_(None))
            .order_by(KnowledgeLibrary.name)
        ).all()
        return [_library_out(s, lib) for lib in libs]


def create_shared(ctx: AppContext, data: LibraryCreate) -> LibraryOut:
    now = ctx.clock.iso()
    with ctx.db.tx() as s:
        lib = KnowledgeLibrary(
            id=ctx.ids.new(),
            name=data.name,
            scope="shared",
            project_id=None,
            description=data.description,
            created_at=now,
            updated_at=now,
        )
        s.add(lib)
        activity.record(s, ctx, kind="library_created", summary=f"Created shared library “{lib.name}”")
        s.flush()
        return _library_out(s, lib)


def patch_library(ctx: AppContext, library_id: str, data: LibraryPatch) -> LibraryOut:
    with ctx.db.tx() as s:
        lib = _require_library(s, library_id)
        if data.name is not None:
            lib.name = data.name
        if data.description is not None:
            lib.description = data.description or None
        lib.updated_at = ctx.clock.iso()
        s.flush()
        return _library_out(s, lib)


def book_knowledge(ctx: AppContext, project_id: str) -> BookKnowledgeOut:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        own = s.scalars(
            select(KnowledgeLibrary).where(
                KnowledgeLibrary.scope == "project",
                KnowledgeLibrary.project_id == project_id,
                KnowledgeLibrary.archived_at.is_(None),
            )
        ).first()
        linked_ids = set(s.scalars(select(LibraryLink.library_id).where(LibraryLink.project_id == project_id)))
        shared = s.scalars(
            select(KnowledgeLibrary).where(KnowledgeLibrary.scope == "shared", KnowledgeLibrary.archived_at.is_(None))
        ).all()
        return BookKnowledgeOut(
            project_library=_library_out(s, own) if own else None,
            linked=[_library_out(s, x) for x in shared if x.id in linked_ids],
            available_shared=[_library_out(s, x) for x in shared if x.id not in linked_ids],
            usable_source_count=len(retrieval.usable_source_ids(s, project_id)),
        )


def link(ctx: AppContext, project_id: str, library_id: str, on: bool) -> BookKnowledgeOut:
    with ctx.db.tx() as s:
        project = require_active(s, project_id)
        lib = _require_library(s, library_id)
        if lib.scope != "shared":
            raise ValidationFailedError("Only shared libraries can be linked to a book.")
        row = s.get(LibraryLink, (project_id, library_id))
        if on and row is None:
            s.add(LibraryLink(project_id=project_id, library_id=library_id, linked_at=ctx.clock.iso()))
            activity.record(
                s,
                ctx,
                kind="library_linked",
                project_id=project_id,
                summary=f"“{project.title}” now uses the shared library “{lib.name}”",
            )
        elif not on and row is not None:
            s.delete(row)
            activity.record(
                s,
                ctx,
                kind="library_unlinked",
                project_id=project_id,
                summary=f"“{project.title}” stopped using the shared library “{lib.name}”",
            )
    return book_knowledge(ctx, project_id)


# ---------- sources ----------


def _source_out(s: Session, src: Source) -> SourceOut:
    lib = s.get(KnowledgeLibrary, src.library_id)
    orig = s.get(OriginalFile, src.original_file_id)
    return SourceOut(
        id=src.id,
        library_id=src.library_id,
        library_name=lib.name if lib else "",
        kind=src.kind,
        title=src.title,
        title_origin=src.title_origin,
        citation_key=src.citation_key,
        original_name=orig.original_name if orig else "",
        file_sha256=src.file_sha256,
        byte_size=orig.byte_size if orig else 0,
        tags=json.loads(src.tags_json),
        enabled=bool(src.enabled),
        status=src.status,
        error=src.error,
        warnings=[WarningOut(**w) for w in json.loads(src.warnings_json)],
        chunk_count=src.chunk_count,
        word_count=src.word_count,
        page_count=src.page_count,
        authors=json.loads(src.authors_json),
        year=src.year,
        publisher=src.publisher,
        url=src.url,
        doi=src.doi,
        created_at=src.created_at,
        indexed_at=src.indexed_at,
        removed_at=src.removed_at,
    )


def _require_source(s: Session, source_id: str) -> Source:
    src = s.get(Source, source_id) if is_ulid(source_id) else None
    if src is None:
        raise NotFoundError("Source not found.")
    return src


def _key_base(title: str) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    words = [w for w in re.findall(r"[a-z0-9]+", ascii_title) if w not in search.STOPWORDS]
    return "-".join(words[:3])[:40] or "source"


def _new_key(s: Session, scope: str, title: str) -> str:
    base = _key_base(title)
    taken = set(s.scalars(select(Source.citation_key).where(Source.key_scope == scope)))
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def _write_chunks(s: Session, ctx: AppContext, src: Source, parsed: ex.Extracted) -> None:
    search.unindex_source(s, src.id)
    s.execute(update(ClaimSupport).where(ClaimSupport.source_id == src.id).values(chunk_id=None))
    for old in s.scalars(select(SourceChunk).where(SourceChunk.source_id == src.id)).all():
        s.delete(old)
    s.flush()
    new_chunks = []
    for c in parsed.chunks:
        row = SourceChunk(
            id=ctx.ids.new(),
            source_id=src.id,
            seq=c.seq,
            heading_path=c.heading_path,
            page_start=c.page_start,
            page_end=c.page_end,
            para_start=c.para_start,
            para_end=c.para_end,
            text=c.text,
        )
        s.add(row)
        new_chunks.append(row)
        search.index_chunk(s, chunk_id=row.id, source_id=src.id, title=src.title, heading=c.heading_path, body=c.text)
    s.flush()
    # Evidence copied from the old chunks is re-linked to the new chunk that still contains the quote.
    for sup in s.scalars(select(ClaimSupport).where(ClaimSupport.source_id == src.id)).all():
        sup.chunk_id = next((c.id for c in new_chunks if sup.quote and sup.quote in c.text), None)
    src.chunk_count, src.word_count, src.page_count = len(parsed.chunks), parsed.word_count, parsed.page_count
    src.text_sha256, src.status, src.error = parsed.text_sha256, "indexed", None
    src.warnings_json = json.dumps(parsed.warnings)
    src.parser_version, src.indexed_at = ex.PARSER_VERSION, ctx.clock.iso()


def import_source(
    ctx: AppContext,
    library_id: str | None,
    filename: str,
    data: bytes,
    *,
    project_id: str | None = None,
    allow_duplicate: bool = False,
) -> SourceImportOut:
    try:
        fmt = detect_format(filename, data)
    except ImportError_ as exc:
        raise ValidationFailedError(str(exc)) from exc
    parsed: ex.Extracted | None = None
    error: str | None = None
    try:
        parsed = ex.extract(fmt, filename, data)
    except ImportError_ as exc:
        error = str(exc)
    with ctx.db.tx() as s:
        if project_id is not None:
            require_active(s, project_id)
            lib = ensure_project_library(s, ctx, project_id)
        else:
            lib = _require_library(s, library_id or "")
        original, _ = _store_original(s, ctx, filename, data, fmt)
        live = select(Source).where(Source.library_id == lib.id, Source.removed_at.is_(None))
        same_file = s.scalars(live.where(Source.file_sha256 == original.sha256)).first()
        if same_file is not None:
            return SourceImportOut(
                source=None, duplicate=DuplicateOut(source_id=same_file.id, title=same_file.title, reason="same_file")
            )
        if parsed is not None and not allow_duplicate:
            same_text = s.scalars(live.where(Source.text_sha256 == parsed.text_sha256)).first()
            if same_text is not None:
                return SourceImportOut(
                    source=None,
                    duplicate=DuplicateOut(source_id=same_text.id, title=same_text.title, reason="same_text"),
                )
        now = ctx.clock.iso()
        title = parsed.title if parsed else (filename.rsplit(".", 1)[0] or "Untitled source")
        scope = lib.project_id if lib.scope == "project" and lib.project_id else "shared"
        src = Source(
            id=ctx.ids.new(),
            library_id=lib.id,
            original_file_id=original.id,
            kind=fmt,
            title=title[:300],
            title_origin=parsed.title_origin if parsed else "file_name",
            citation_key=_new_key(s, scope, title),
            key_scope=scope,
            file_sha256=original.sha256,
            text_sha256=None,
            tags_json="[]",
            enabled=1,
            status="pending",
            error=None,
            warnings_json="[]",
            chunk_count=0,
            word_count=0,
            authors_json="[]",
            parser_version=ex.PARSER_VERSION,
            created_at=now,
            updated_at=now,
        )
        s.add(src)
        s.flush()
        if parsed is not None:
            _write_chunks(s, ctx, src, parsed)
        else:
            src.status, src.error = "failed", error
        activity.record(
            s,
            ctx,
            kind="source_imported",
            project_id=lib.project_id,
            ref_type="source",
            ref_id=src.id,
            summary=f"Added source “{src.title}” to “{lib.name}” ({src.status})",
        )
        s.flush()
        return SourceImportOut(source=_source_out(s, src))


def list_sources(
    ctx: AppContext, *, library_id: str | None = None, project_id: str | None = None, include_removed: bool = False
) -> list[SourceOut]:
    with ctx.db.tx() as s:
        if project_id is not None:
            require_project(s, project_id)
            libs = retrieval.library_ids(s, project_id)
        else:
            libs = [_require_library(s, library_id or "").id]
        stmt = select(Source).where(Source.library_id.in_(libs)).order_by(Source.title)
        if not include_removed:
            stmt = stmt.where(Source.removed_at.is_(None))
        return [_source_out(s, x) for x in s.scalars(stmt).all()]


def get_source(ctx: AppContext, source_id: str) -> SourceOut:
    with ctx.db.tx() as s:
        return _source_out(s, _require_source(s, source_id))


def patch_source(ctx: AppContext, source_id: str, data: SourcePatch) -> SourceOut:
    with ctx.db.tx() as s:
        src = _require_source(s, source_id)
        if src.removed_at is not None:
            raise ConflictError("This source was removed.")
        if data.title is not None and data.title != src.title:
            src.title, src.title_origin = data.title, "author"
            search.retitle_source(s, src.id, data.title)
        if data.tags is not None:
            src.tags_json = json.dumps(sorted(dict.fromkeys(data.tags)))
        if data.enabled is not None and bool(src.enabled) != data.enabled:
            src.enabled = 1 if data.enabled else 0
            verb = "Enabled" if data.enabled else "Disabled"
            lib = s.get(KnowledgeLibrary, src.library_id)
            activity.record(
                s,
                ctx,
                kind="source_toggled",
                project_id=lib.project_id if lib else None,
                summary=f"{verb} source “{src.title}” for AI use",
                ref_type="source",
                ref_id=src.id,
            )
        fields = data.model_fields_set
        if "authors" in fields:
            src.authors_json = json.dumps(data.authors or [])
        for name in ("year", "publisher", "url", "doi"):
            if name in fields:
                setattr(src, name, getattr(data, name) or None)
        src.updated_at = ctx.clock.iso()
        s.flush()
        return _source_out(s, src)


def remove_source(ctx: AppContext, source_id: str) -> SourceOut:
    """Removes the source from search and AI use. The original upload and the evidence quotes stay."""
    with ctx.db.tx() as s:
        src = _require_source(s, source_id)
        if src.removed_at is None:
            search.unindex_source(s, src.id)
            s.execute(update(ClaimSupport).where(ClaimSupport.source_id == src.id).values(chunk_id=None))
            for c in s.scalars(select(SourceChunk).where(SourceChunk.source_id == src.id)).all():
                s.delete(c)
            src.removed_at, src.enabled, src.chunk_count = ctx.clock.iso(), 0, 0
            lib = s.get(KnowledgeLibrary, src.library_id)
            activity.record(
                s,
                ctx,
                kind="source_removed",
                project_id=lib.project_id if lib else None,
                summary=f"Removed source “{src.title}”",
                ref_type="source",
                ref_id=src.id,
            )
        s.flush()
        return _source_out(s, src)


def reindex_source(ctx: AppContext, source_id: str) -> SourceOut:
    with ctx.db.tx() as s:
        src = _require_source(s, source_id)
        if src.removed_at is not None:
            raise ConflictError("This source was removed. Import the file again to use it.")
        original = s.get(OriginalFile, src.original_file_id)
        if original is None:  # pragma: no cover - foreign key
            raise NotFoundError("The original file is missing.")
        data, name = _read_original(ctx, original), original.original_name
    try:
        parsed = ex.extract(src.kind, name, data)
    except ImportError_ as exc:
        with ctx.db.tx() as s:
            live = _require_source(s, source_id)
            live.status, live.error = "failed", str(exc)
            s.flush()
            return _source_out(s, live)
    with ctx.db.tx() as s:
        live = _require_source(s, source_id)
        _write_chunks(s, ctx, live, parsed)
        live.updated_at = ctx.clock.iso()
        s.flush()
        return _source_out(s, live)


def source_text(ctx: AppContext, source_id: str) -> SourceTextOut:
    with ctx.db.tx() as s:
        src = _require_source(s, source_id)
        chunks = s.scalars(select(SourceChunk).where(SourceChunk.source_id == src.id).order_by(SourceChunk.seq)).all()
        return SourceTextOut(
            source=_source_out(s, src),
            chunks=[
                ChunkOut(
                    id=c.id,
                    seq=c.seq,
                    heading_path=c.heading_path,
                    locator=ex.locator(c.page_start, c.page_end, c.para_start, c.para_end),
                    text=c.text,
                )
                for c in chunks
            ],
        )


# ---------- search ----------


def run_search(
    ctx: AppContext, query: str, *, project_id: str | None = None, library_id: str | None = None, limit: int = 20
) -> SearchOut:
    with ctx.db.tx() as s:
        if project_id is not None:
            require_project(s, project_id)
            ids = retrieval.usable_source_ids(s, project_id)
        else:
            lib = _require_library(s, library_id or "")
            ids = list(
                s.scalars(
                    select(Source.id).where(
                        Source.library_id == lib.id,
                        Source.enabled == 1,
                        Source.status == "indexed",
                        Source.removed_at.is_(None),
                    )
                )
            )
        hits, mode = search.search(s, source_ids=ids, query=query, limit=limit)
        return SearchOut(
            query=query,
            mode=mode,
            hits=[
                SearchHitOut(
                    chunk_id=h.chunk_id,
                    source_id=h.source_id,
                    source_title=h.title,
                    citation_key=h.citation_key,
                    locator=h.locator,
                    heading_path=h.heading_path,
                    snippet=[SnippetPart(**p) for p in h.snippet],
                    reasons=h.reasons,
                    score=h.score,
                )
                for h in hits
            ],
            searched_sources=len(ids),
            semantic_note=SEMANTIC_NOTE,
        )


# ---------- citation metadata ----------


def citations(ctx: AppContext, project_id: str) -> list[CitationOut]:
    """Every source cited in the book's current text, with only the metadata that is actually known."""
    with ctx.db.tx() as s:
        require_project(s, project_id)
        heads = s.execute(
            select(Chapter.id, ChapterRevision.source_md)
            .join(ChapterRevision, ChapterRevision.id == Chapter.head_revision_id)
            .where(Chapter.project_id == project_id, Chapter.archived_at.is_(None))
        ).all()
        used: dict[str, set[str]] = {}
        for chapter_id, md in heads:
            for key in _CITE_KEY.findall(md or ""):
                used.setdefault(key.rstrip(".,;:"), set()).add(chapter_id)
        libs = retrieval.library_ids(s, project_id)
        out: list[CitationOut] = []
        for src in s.scalars(select(Source).where(Source.library_id.in_(libs)).order_by(Source.citation_key)).all():
            if src.citation_key not in used:
                continue
            out.append(
                CitationOut(
                    id=src.citation_key,
                    title=src.title,
                    author=json.loads(src.authors_json),
                    issued=src.year,
                    publisher=src.publisher,
                    URL=src.url,
                    DOI=src.doi,
                    source_id=src.id,
                    cited_in_chapters=len(used[src.citation_key]),
                )
            )
        return out


def source_titles(s: Session, ids: list[str]) -> dict[str, Any]:
    return {x.id: x for x in s.scalars(select(Source).where(Source.id.in_(ids)))} if ids else {}
