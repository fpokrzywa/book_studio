"""HTTP routes for publishing: profile, builds, covers, previews, reports and the package (Phase 07)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status
from fastapi.responses import FileResponse, HTMLResponse

from pbs_core.api.routes import ERRORS, Ctx
from pbs_core.contracts_publishing import (
    BuildIn,
    BuildOut,
    CoverSpecOut,
    PackageOut,
    PreviewHtmlOut,
    ProfileIn,
    ProfileOut,
    PublicationOut,
)
from pbs_core.services import publishing

router = APIRouter(prefix="/api/projects/{project_id}/publishing", responses=ERRORS, tags=["publishing"])

_INLINE = {"application/pdf", "text/html; charset=utf-8", "image/jpeg", "application/json", "text/plain; charset=utf-8"}


def _file(path: Any, name: str, media: str, inline: bool) -> FileResponse:
    disposition = "inline" if inline and media in _INLINE else "attachment"
    resp = FileResponse(path, media_type=media, filename=name, content_disposition_type=disposition)
    # Exported HTML is the author's own book, but never let it run scripts or load anything.
    resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@router.get("/profile")
def get_profile(ctx: Ctx, project_id: str) -> ProfileOut:
    return publishing.get_profile(ctx, project_id)


@router.put("/profile")
def put_profile(ctx: Ctx, project_id: str, body: ProfileIn) -> ProfileOut:
    return publishing.put_profile(ctx, project_id, body)


@router.post("/build", status_code=status.HTTP_201_CREATED)
def build(ctx: Ctx, project_id: str, body: BuildIn) -> BuildOut:
    return publishing.build(ctx, project_id, body)


@router.get("/cover-spec")
def cover_spec(ctx: Ctx, project_id: str) -> CoverSpecOut:
    return publishing.cover_spec(ctx, project_id)


@router.post("/covers", status_code=status.HTTP_201_CREATED)
def build_covers(ctx: Ctx, project_id: str) -> BuildOut:
    return publishing.build_covers(ctx, project_id)


@router.post("/package", status_code=status.HTTP_201_CREATED)
def build_package(ctx: Ctx, project_id: str) -> PackageOut:
    return publishing.build_package(ctx, project_id)


@router.get("/publications")
def list_publications(ctx: Ctx, project_id: str) -> list[PublicationOut]:
    return publishing.list_publications(ctx, project_id)


@router.get("/publications/{pub_id}/report")
def report(ctx: Ctx, project_id: str, pub_id: str) -> dict[str, Any]:
    return publishing.report(ctx, project_id, pub_id)


@router.get("/publications/{pub_id}/report.html", response_class=HTMLResponse)
def report_html(ctx: Ctx, project_id: str, pub_id: str) -> HTMLResponse:
    resp = HTMLResponse(publishing.report_html(ctx, project_id, pub_id))
    resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    return resp


@router.get("/publications/{pub_id}/file")
def publication_file(ctx: Ctx, project_id: str, pub_id: str, inline: bool = False) -> FileResponse:
    path, name, media = publishing.publication_file(ctx, project_id, pub_id)
    return _file(path, name, media, inline)


@router.get("/publications/{pub_id}/package-file")
def package_file(ctx: Ctx, project_id: str, pub_id: str, name: str, inline: bool = False) -> FileResponse:
    path, fname, media = publishing.package_file(ctx, project_id, pub_id, name)
    return _file(path, fname, media, inline)


@router.get("/preview/html")
def preview_html(ctx: Ctx, project_id: str) -> PreviewHtmlOut:
    return publishing.preview_html(ctx, project_id)


@router.get("/preview/pdf-page/{page}", responses={200: {"content": {"image/png": {}}}})
def preview_pdf_page(ctx: Ctx, project_id: str, page: int) -> Response:
    png, total = publishing.preview_pdf_pages(ctx, project_id, page)
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "X-Page-Count": str(total),
            "X-Preview-Note": "rendered page image, not the PDF file",
            "Cache-Control": "no-store",
        },
    )
