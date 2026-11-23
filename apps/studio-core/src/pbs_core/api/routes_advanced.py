"""HTTP routes for Phase 08: pen names and voice, translation editions, narration and recorded interviews."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Query, UploadFile, status
from fastapi.responses import FileResponse

from pbs_core.api.routes import ERRORS, Ctx, read_upload
from pbs_core.contracts_advanced import (
    AudioExportOut,
    ChapterLinksOut,
    EditionIn,
    EditionOut,
    IssueStateIn,
    MediaStatusOut,
    NarrationOut,
    NarrationSettingsIn,
    PenNameIn,
    ProjectVoiceIn,
    ProjectVoiceOut,
    QuoteIn,
    QuoteOut,
    RecordingOut,
    SeriesOut,
    SpeakerIn,
    SynthesizeOut,
    TermsIn,
    TranscribeIn,
    TranslateIn,
)
from pbs_core.contracts_ai import JobOut
from pbs_core.contracts_auth import TaskOut
from pbs_core.contracts_knowledge import AuthorProfileOut
from pbs_core.services import media, series, tasks, translation, voice

router = APIRouter(prefix="/api", responses=ERRORS)


def _audio(path: Any, name: str, media_type: str) -> FileResponse:
    resp = FileResponse(path, media_type=media_type, filename=name, content_disposition_type="inline")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


# ---------- pen names and the voice used by a book ----------


@router.put("/voice/profiles/{profile_id}/pen-name", tags=["voice"])
def set_pen_name(ctx: Ctx, profile_id: str, body: PenNameIn) -> AuthorProfileOut:
    out: AuthorProfileOut = voice.set_pen_name(ctx, profile_id, body)
    return out


@router.get("/projects/{project_id}/voice", tags=["voice"])
def project_voice(ctx: Ctx, project_id: str) -> ProjectVoiceOut:
    out: ProjectVoiceOut = voice.project_voice(ctx, project_id)
    return out


@router.put("/projects/{project_id}/voice", tags=["voice"])
def set_project_voice(ctx: Ctx, project_id: str, body: ProjectVoiceIn) -> ProjectVoiceOut:
    out: ProjectVoiceOut = voice.set_project_voice(ctx, project_id, body.author_profile_id)
    return out


@router.get("/projects/{project_id}/series", tags=["series"])
def series_of_project(ctx: Ctx, project_id: str) -> SeriesOut | None:
    return series.series_for_project(ctx, project_id)


# ---------- translation editions ----------


@router.get("/projects/{project_id}/editions", tags=["translation"])
def list_editions(ctx: Ctx, project_id: str) -> list[EditionOut]:
    return translation.list_editions(ctx, project_id)


@router.post("/projects/{project_id}/editions", tags=["translation"], status_code=status.HTTP_201_CREATED)
def create_edition(ctx: Ctx, project_id: str, body: EditionIn) -> EditionOut:
    return translation.create_edition(ctx, project_id, body)


@router.get("/projects/{project_id}/editions/{edition_id}", tags=["translation"])
def get_edition(ctx: Ctx, project_id: str, edition_id: str) -> EditionOut:
    return translation.get_edition(ctx, project_id, edition_id)


@router.put("/projects/{project_id}/editions/{edition_id}/terms", tags=["translation"])
def set_terms(ctx: Ctx, project_id: str, edition_id: str, body: TermsIn) -> EditionOut:
    return translation.set_terms(ctx, project_id, edition_id, dict(body.term_map))


@router.post(
    "/projects/{project_id}/editions/{edition_id}/translate", tags=["translation"], status_code=status.HTTP_202_ACCEPTED
)
def translate(ctx: Ctx, project_id: str, edition_id: str, body: TranslateIn) -> JobOut:
    return translation.translate(ctx, project_id, edition_id, body)


@router.put("/projects/{project_id}/editions/{edition_id}/chapters/{chapter_id}/issues/{index}", tags=["translation"])
def review_issue(
    ctx: Ctx, project_id: str, edition_id: str, chapter_id: str, index: int, body: IssueStateIn
) -> EditionOut:
    return translation.review_issue(ctx, project_id, edition_id, chapter_id, index, body.state)


@router.get("/projects/{project_id}/chapters/{chapter_id}/translations", tags=["translation"])
def chapter_links(ctx: Ctx, project_id: str, chapter_id: str) -> ChapterLinksOut:
    return translation.chapter_links(ctx, project_id, chapter_id)


# ---------- narration ----------


@router.get("/media/status", tags=["media"])
def media_status(ctx: Ctx) -> MediaStatusOut:
    return media.media_status(ctx)


@router.get("/projects/{project_id}/narration", tags=["media"])
def narration(ctx: Ctx, project_id: str) -> NarrationOut:
    return media.overview(ctx, project_id)


@router.put("/projects/{project_id}/narration/settings", tags=["media"])
def narration_settings(ctx: Ctx, project_id: str, body: NarrationSettingsIn) -> NarrationOut:
    return media.set_settings(ctx, project_id, body)


@router.post("/projects/{project_id}/narration/chapters/{chapter_id}/prepare", tags=["media"])
def prepare(ctx: Ctx, project_id: str, chapter_id: str) -> dict[str, Any]:
    return media.prepare(ctx, project_id, chapter_id)


@router.get("/projects/{project_id}/narration/chapters/{chapter_id}", tags=["media"])
def chapter_script(ctx: Ctx, project_id: str, chapter_id: str) -> dict[str, Any]:
    return media.get_script(ctx, project_id, chapter_id)


@router.post("/projects/{project_id}/narration/chapters/{chapter_id}/synthesize", tags=["media"])
def synthesize(
    ctx: Ctx, project_id: str, chapter_id: str, limit: Annotated[int, Query(ge=1, le=50)] = 5
) -> SynthesizeOut:
    return media.synthesize(ctx, project_id, chapter_id, limit)


@router.get("/projects/{project_id}/narration/parts/{chunk_id}/audio", tags=["media"], response_class=FileResponse)
def chunk_audio(ctx: Ctx, project_id: str, chunk_id: str) -> FileResponse:
    return _audio(media.chunk_audio(ctx, project_id, chunk_id), f"{chunk_id}.wav", "audio/wav")


@router.post("/projects/{project_id}/narration/export-task", tags=["media"], status_code=status.HTTP_202_ACCEPTED)
def export_narration_task(ctx: Ctx, project_id: str) -> TaskOut:
    return tasks.enqueue(ctx, "narration.export", project_id)


@router.post("/projects/{project_id}/narration/export", tags=["media"], status_code=status.HTTP_201_CREATED)
def export_audio(ctx: Ctx, project_id: str) -> AudioExportOut:
    return media.export_audio(ctx, project_id)


@router.get("/projects/{project_id}/narration/exports/{file_name}", tags=["media"], response_class=FileResponse)
def export_file(ctx: Ctx, project_id: str, file_name: str) -> FileResponse:
    resp = FileResponse(media.export_file(ctx, project_id, file_name), media_type="application/zip", filename=file_name)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


# ---------- recorded interviews ----------


@router.get("/projects/{project_id}/recordings", tags=["media"])
def list_recordings(ctx: Ctx, project_id: str) -> list[RecordingOut]:
    return media.list_recordings(ctx, project_id)


@router.post("/projects/{project_id}/recordings", tags=["media"], status_code=status.HTTP_201_CREATED)
async def import_recording(
    ctx: Ctx,
    project_id: str,
    file: Annotated[UploadFile, File()],
    rights_confirmed: Annotated[bool, Form()] = False,
    title: Annotated[str, Form(max_length=200)] = "",
    rights_note: Annotated[str, Form(max_length=1000)] = "",
) -> RecordingOut:
    data = await read_upload(file, ctx.settings.max_upload_mb)
    return media.import_recording(ctx, project_id, file.filename or "recording", data, title=title,
                                  rights_confirmed=rights_confirmed, rights_note=rights_note)  # fmt: skip


@router.get("/projects/{project_id}/recordings/{recording_id}", tags=["media"])
def get_recording(ctx: Ctx, project_id: str, recording_id: str) -> RecordingOut:
    return media.get_recording(ctx, project_id, recording_id)


@router.get("/projects/{project_id}/recordings/{recording_id}/audio", tags=["media"], response_class=FileResponse)
def recording_audio(ctx: Ctx, project_id: str, recording_id: str) -> FileResponse:
    path, mime = media.recording_file(ctx, project_id, recording_id)
    return _audio(path, f"{recording_id}", mime)


@router.post("/projects/{project_id}/recordings/{recording_id}/transcribe", tags=["media"])
def transcribe(ctx: Ctx, project_id: str, recording_id: str, body: TranscribeIn) -> RecordingOut:
    return media.transcribe(ctx, project_id, recording_id, body)


@router.put("/projects/{project_id}/recordings/{recording_id}/segments/{segment_id}/speaker", tags=["media"])
def set_speaker(ctx: Ctx, project_id: str, recording_id: str, segment_id: str, body: SpeakerIn) -> RecordingOut:
    return media.set_speaker(ctx, project_id, recording_id, segment_id, body)


@router.post(
    "/projects/{project_id}/recordings/{recording_id}/quotes", tags=["media"], status_code=status.HTTP_201_CREATED
)
def quote(ctx: Ctx, project_id: str, recording_id: str, body: QuoteIn) -> QuoteOut:
    return QuoteOut.model_validate(media.quote(ctx, project_id, recording_id, body))
