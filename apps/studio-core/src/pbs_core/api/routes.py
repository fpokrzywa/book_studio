"""HTTP routes. Thin: validate -> call service -> return contract model."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import FileResponse

from pbs_core import __version__
from pbs_core.context import AppContext
from pbs_core.contracts import (
    ActivityOut,
    CapabilityOut,
    ChapterContentOut,
    ChapterCreate,
    ChapterOut,
    ChapterPatch,
    ChapterSaveIn,
    ChapterSaveOut,
    ExportCreate,
    ExportOut,
    Problem,
    ProjectCreate,
    ProjectList,
    ProjectOut,
    ProjectPatch,
    ProjectSort,
    ProjectType,
    PublicationFormat,
    RevisionMetaOut,
    SystemInfoOut,
)
from pbs_core.services import activity, capabilities, chapters, exports, projects


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
    mode = ctx.setting("privacy_mode")
    return SystemInfoOut(
        app_version=__version__,
        schema_revision=ctx.schema_revision,
        workspace_path=str(ctx.workspace.root),
        privacy_mode="cloud_allowed" if mode == "cloud_allowed" else "local_only",
        env=ctx.settings.env,
    )


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
    return exports.export_markdown(ctx, project_id)


@api.get("/projects/{project_id}/exports", tags=["exports"])
def list_exports(ctx: Ctx, project_id: str) -> list[ExportOut]:
    return exports.list_exports(ctx, project_id)


@api.get(
    "/projects/{project_id}/exports/{export_id}/file",
    tags=["exports"],
    response_class=FileResponse,
)
def download_export(ctx: Ctx, project_id: str, export_id: str) -> FileResponse:
    path, name = exports.export_file(ctx, project_id, export_id)
    return FileResponse(path, media_type="text/markdown; charset=utf-8", filename=name)


@api.get("/activity", tags=["activity"])
def list_activity(
    ctx: Ctx,
    project_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ActivityOut]:
    return activity.list_activity(ctx, project_id=project_id, limit=limit)
