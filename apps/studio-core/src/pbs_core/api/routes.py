"""HTTP routes. Thin: validate -> call service -> return contract model."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import FileResponse

from pbs_core import __version__
from pbs_core.context import AppContext
from pbs_core.contracts import (
    ActivityOut,
    AssetOut,
    BackupOut,
    BookOut,
    CapabilityOut,
    ChapterContentOut,
    ChapterCreate,
    ChapterMove,
    ChapterOut,
    ChapterPatch,
    ChapterSaveIn,
    ChapterSaveOut,
    CompareOut,
    DraftIn,
    ExportCreate,
    ExportOut,
    ImportCommitIn,
    ImportCommitOut,
    ImportPreviewOut,
    PreviewIn,
    PreviewOut,
    Problem,
    ProjectCreate,
    ProjectList,
    ProjectOut,
    ProjectPatch,
    ProjectSort,
    ProjectType,
    PublicationFormat,
    RestoreIn,
    RestoreOut,
    RevisionMetaOut,
    RevisionOut,
    RevisionTagIn,
    SystemInfoOut,
)
from pbs_core.domain.errors import DomainError
from pbs_core.services import (
    activity,
    assets,
    backup,
    capabilities,
    chapters,
    documents,
    exports,
    imports,
    projects,
)

SAFE_DOWNLOAD_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox",
}


class PayloadTooLargeError(DomainError):
    status = 413
    code = "payload_too_large"


async def read_upload(upload: UploadFile, limit_mb: int) -> bytes:
    """Read an upload in chunks, refusing anything over the limit without buffering it all."""
    limit = limit_mb * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(1024 * 1024):
        total += len(chunk)
        if total > limit:
            raise PayloadTooLargeError(f"The file is larger than the {limit_mb} MB limit.")
        chunks.append(chunk)
    return b"".join(chunks)


def get_ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx


Ctx = Annotated[AppContext, Depends(get_ctx)]
ERRORS: dict[int | str, dict[str, object]] = {
    400: {"model": Problem},
    401: {"model": Problem},
    403: {"model": Problem},
    404: {"model": Problem},
    409: {"model": Problem},
    422: {"model": Problem},
}

health = APIRouter()
api = APIRouter(prefix="/api", responses=ERRORS)


@health.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@api.get("/system/info", tags=["system"])
def system_info(ctx: Ctx) -> SystemInfoOut:
    mode = ctx.setting("privacy_mode") if ctx.settings.allow_cloud else "local_only"  # operator switch wins
    running, seen = _worker_state(ctx)
    return SystemInfoOut(
        app_version=__version__,
        schema_revision=ctx.schema_revision,
        workspace_path=str(ctx.workspace.root),
        privacy_mode="cloud_allowed" if mode == "cloud_allowed" else "local_only",
        env=ctx.settings.env,
        deployment=ctx.settings.deployment,
        worker_running=running,
        worker_last_seen_at=seen,
    )


def _worker_state(ctx: AppContext) -> tuple[bool, str | None]:
    """In-process runner, or a separate worker whose heartbeat file is under a minute old."""
    import time

    from pbs_core.jobs.runner import HEARTBEAT_FILE

    if ctx.jobs is not None:
        return True, ctx.clock.iso()
    path = ctx.workspace.runtime_dir / HEARTBEAT_FILE
    try:
        age = time.time() - path.stat().st_mtime
        seen = path.read_text(encoding="ascii").strip() or None
    except OSError:
        return False, None
    return age < 60, seen


@api.get("/system/capabilities", tags=["system"])
def system_capabilities() -> list[CapabilityOut]:
    return capabilities.report()


@api.get("/projects", tags=["projects"])
def list_projects(
    ctx: Ctx,
    q: Annotated[str | None, Query(max_length=200)] = None,
    project_type: ProjectType | None = None,
    language: Annotated[str | None, Query(max_length=35)] = None,
    publication_format: PublicationFormat | None = None,
    status_filter: Annotated[Literal["active", "archived", "all"], Query(alias="status")] = "active",
    sort: ProjectSort = "updated_at",
    order: Literal["asc", "desc"] = "desc",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectList:
    return projects.list_projects(
        ctx,
        q=q,
        project_type=project_type,
        language=language,
        publication_format=publication_format,
        status=status_filter,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )


@api.post("/projects", status_code=status.HTTP_201_CREATED, tags=["projects"])
def create_project(ctx: Ctx, body: ProjectCreate) -> ProjectOut:
    return projects.create_project(ctx, body)


@api.get("/projects/{project_id}", tags=["projects"])
def get_project(ctx: Ctx, project_id: str) -> ProjectOut:
    return projects.get_project(ctx, project_id)


@api.patch("/projects/{project_id}", tags=["projects"])
def update_project(ctx: Ctx, project_id: str, body: ProjectPatch) -> ProjectOut:
    return projects.update_project(ctx, project_id, body)


@api.post("/projects/{project_id}/archive", tags=["projects"])
def archive_project(ctx: Ctx, project_id: str) -> ProjectOut:
    return projects.set_archived(ctx, project_id, True)


@api.post("/projects/{project_id}/unarchive", tags=["projects"])
def unarchive_project(ctx: Ctx, project_id: str) -> ProjectOut:
    return projects.set_archived(ctx, project_id, False)


@api.post("/projects/{project_id}/duplicate", status_code=status.HTTP_201_CREATED, tags=["projects"])
def duplicate_project(ctx: Ctx, project_id: str) -> ProjectOut:
    return projects.duplicate_project(ctx, project_id)


@api.get("/projects/{project_id}/chapters", tags=["chapters"])
def list_chapters(ctx: Ctx, project_id: str) -> list[ChapterOut]:
    return chapters.list_chapters(ctx, project_id)


@api.post("/projects/{project_id}/chapters", status_code=status.HTTP_201_CREATED, tags=["chapters"])
def create_chapter(ctx: Ctx, project_id: str, body: ChapterCreate) -> ChapterOut:
    return chapters.create_chapter(ctx, project_id, body)


@api.get("/projects/{project_id}/chapters/{chapter_id}", tags=["chapters"])
def get_chapter(ctx: Ctx, project_id: str, chapter_id: str) -> ChapterOut:
    return chapters.get_chapter(ctx, project_id, chapter_id)


@api.patch("/projects/{project_id}/chapters/{chapter_id}", tags=["chapters"])
def update_chapter(ctx: Ctx, project_id: str, chapter_id: str, body: ChapterPatch) -> ChapterOut:
    return chapters.update_chapter(ctx, project_id, chapter_id, body)


@api.post(
    "/projects/{project_id}/chapters/{chapter_id}/archive",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["chapters"],
)
def archive_chapter(ctx: Ctx, project_id: str, chapter_id: str) -> None:
    chapters.archive_chapter(ctx, project_id, chapter_id)


@api.get("/projects/{project_id}/chapters/{chapter_id}/content", tags=["chapters"])
def get_content(ctx: Ctx, project_id: str, chapter_id: str) -> ChapterContentOut:
    return chapters.get_content(ctx, project_id, chapter_id)


@api.put("/projects/{project_id}/chapters/{chapter_id}/content", tags=["chapters"])
def save_content(ctx: Ctx, project_id: str, chapter_id: str, body: ChapterSaveIn) -> ChapterSaveOut:
    return chapters.save_content(ctx, project_id, chapter_id, body)


@api.get("/projects/{project_id}/chapters/{chapter_id}/revisions", tags=["chapters"])
def list_revisions(ctx: Ctx, project_id: str, chapter_id: str) -> list[RevisionMetaOut]:
    return chapters.list_revisions(ctx, project_id, chapter_id)


@api.post("/projects/{project_id}/exports", status_code=status.HTTP_201_CREATED, tags=["exports"])
def create_export(ctx: Ctx, project_id: str, body: ExportCreate) -> ExportOut:
    return exports.export_project(ctx, project_id, body.format)


@api.get("/projects/{project_id}/exports", tags=["exports"])
def list_exports(ctx: Ctx, project_id: str) -> list[ExportOut]:
    return exports.list_exports(ctx, project_id)


@api.get(
    "/projects/{project_id}/exports/{export_id}/file",
    tags=["exports"],
    response_class=FileResponse,
)
def download_export(ctx: Ctx, project_id: str, export_id: str) -> FileResponse:
    path, name, media_type = exports.export_file(ctx, project_id, export_id)
    return FileResponse(path, media_type=media_type, filename=name, headers=SAFE_DOWNLOAD_HEADERS)


@api.get("/activity", tags=["activity"])
def list_activity(
    ctx: Ctx,
    project_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ActivityOut]:
    return activity.list_activity(ctx, project_id=project_id, limit=limit)


# ---------------- Phase 02: book, tree, drafts, history, preview, assets, imports, backups ----------------


@api.get("/projects/{project_id}/book", tags=["projects"])
def get_book(ctx: Ctx, project_id: str) -> BookOut:
    return BookOut(project=projects.get_project(ctx, project_id), chapters=chapters.list_chapters(ctx, project_id))


@api.post("/projects/{project_id}/chapters/{chapter_id}/move", tags=["chapters"])
def move_chapter(ctx: Ctx, project_id: str, chapter_id: str, body: ChapterMove) -> list[ChapterOut]:
    return chapters.move_chapter(ctx, project_id, chapter_id, body)


@api.put("/projects/{project_id}/chapters/{chapter_id}/draft", tags=["chapters"])
def put_draft(ctx: Ctx, project_id: str, chapter_id: str, body: DraftIn) -> ChapterContentOut:
    return chapters.put_draft(ctx, project_id, chapter_id, body)


@api.delete("/projects/{project_id}/chapters/{chapter_id}/draft", tags=["chapters"])
def discard_draft(ctx: Ctx, project_id: str, chapter_id: str) -> ChapterContentOut:
    return chapters.discard_draft(ctx, project_id, chapter_id)


@api.get("/projects/{project_id}/chapters/{chapter_id}/compare", tags=["chapters"])
def compare_revisions(
    ctx: Ctx,
    project_id: str,
    chapter_id: str,
    from_no: Annotated[int, Query(alias="from", ge=1)],
    to_no: Annotated[int, Query(alias="to", ge=1)],
) -> CompareOut:
    return chapters.compare(ctx, project_id, chapter_id, from_no, to_no)


@api.get("/projects/{project_id}/chapters/{chapter_id}/revisions/{revision_no}", tags=["chapters"])
def get_revision(ctx: Ctx, project_id: str, chapter_id: str, revision_no: int) -> RevisionOut:
    return chapters.get_revision(ctx, project_id, chapter_id, revision_no)


@api.post("/projects/{project_id}/chapters/{chapter_id}/revisions/{revision_no}/restore", tags=["chapters"])
def restore_revision(ctx: Ctx, project_id: str, chapter_id: str, revision_no: int, body: RestoreIn) -> ChapterSaveOut:
    return chapters.restore_revision(ctx, project_id, chapter_id, revision_no, body)


@api.put("/projects/{project_id}/chapters/{chapter_id}/revisions/{revision_no}/tag", tags=["chapters"])
def tag_revision(ctx: Ctx, project_id: str, chapter_id: str, revision_no: int, body: RevisionTagIn) -> RevisionMetaOut:
    return chapters.tag_revision(ctx, project_id, chapter_id, revision_no, body)


@api.post("/projects/{project_id}/preview", tags=["documents"])
def preview(ctx: Ctx, project_id: str, body: PreviewIn) -> PreviewOut:
    return documents.preview(ctx, project_id, body.source_md)


@api.get("/projects/{project_id}/assets", tags=["assets"])
def list_assets(ctx: Ctx, project_id: str) -> list[AssetOut]:
    return assets.list_assets(ctx, project_id)


@api.post("/projects/{project_id}/assets", status_code=status.HTTP_201_CREATED, tags=["assets"])
async def upload_asset(ctx: Ctx, project_id: str, file: Annotated[UploadFile, File()]) -> AssetOut:
    data = await read_upload(file, min(ctx.settings.max_upload_mb, 25))
    return assets.upload(ctx, project_id, data, file.filename)


@api.get("/projects/{project_id}/assets/{short_hash}", tags=["assets"], response_class=FileResponse)
def get_asset(ctx: Ctx, project_id: str, short_hash: str) -> FileResponse:
    path, mime = assets.asset_file(ctx, project_id, short_hash)
    headers = {**SAFE_DOWNLOAD_HEADERS, "Cache-Control": "private, max-age=86400"}
    return FileResponse(path, media_type=mime, headers=headers)


@api.post("/imports", status_code=status.HTTP_201_CREATED, tags=["imports"])
async def create_import(
    ctx: Ctx,
    file: Annotated[UploadFile, File()],
    target_project_id: Annotated[str | None, Form()] = None,
) -> ImportPreviewOut:
    data = await read_upload(file, ctx.settings.max_upload_mb)
    return imports.create_import(ctx, file.filename or "upload", data, target_project_id or None)


@api.get("/imports/{import_id}", tags=["imports"])
def get_import(ctx: Ctx, import_id: str) -> ImportPreviewOut:
    return imports.get_import(ctx, import_id)


@api.post("/imports/{import_id}/commit", tags=["imports"])
def commit_import(ctx: Ctx, import_id: str, body: ImportCommitIn) -> ImportCommitOut:
    return imports.commit_import(ctx, import_id, body)


@api.post("/imports/{import_id}/cancel", tags=["imports"])
def cancel_import(ctx: Ctx, import_id: str) -> ImportPreviewOut:
    return imports.cancel_import(ctx, import_id)


@api.get("/imports/{import_id}/original", tags=["imports"], response_class=FileResponse)
def download_original(ctx: Ctx, import_id: str) -> FileResponse:
    path, name = imports.original_file(ctx, import_id)
    return FileResponse(path, media_type="application/octet-stream", filename=name, headers=SAFE_DOWNLOAD_HEADERS)


@api.get("/projects/{project_id}/imports", tags=["imports"])
def list_imports(ctx: Ctx, project_id: str) -> list[ImportPreviewOut]:
    return imports.list_imports(ctx, project_id)


@api.post("/projects/{project_id}/backups", status_code=status.HTTP_201_CREATED, tags=["backups"])
def create_backup(ctx: Ctx, project_id: str) -> BackupOut:
    return backup.create_backup(ctx, project_id)


@api.get("/projects/{project_id}/backups", tags=["backups"])
def list_backups(ctx: Ctx, project_id: str) -> list[BackupOut]:
    return backup.list_backups(ctx, project_id)


@api.get("/backups/{backup_id}/file", tags=["backups"], response_class=FileResponse)
def download_backup(ctx: Ctx, backup_id: str) -> FileResponse:
    path, name = backup.backup_file(ctx, backup_id)
    return FileResponse(path, media_type="application/zip", filename=name, headers=SAFE_DOWNLOAD_HEADERS)


@api.post("/backups/restore", status_code=status.HTTP_201_CREATED, tags=["backups"])
async def restore_backup(ctx: Ctx, file: Annotated[UploadFile, File()]) -> RestoreOut:
    data = await read_upload(file, ctx.settings.max_backup_mb)
    return backup.restore_backup(ctx, data)
