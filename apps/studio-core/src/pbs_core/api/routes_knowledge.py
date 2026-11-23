"""HTTP routes for the knowledge workspace, evidence ledger, author voice and interviews (Phase 04)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from pbs_core.api.routes import ERRORS, Ctx, read_upload
from pbs_core.contracts_knowledge import (
    AnswerIn,
    AuthorProfileCreate,
    AuthorProfileOut,
    AuthorProfilePatch,
    BookKnowledgeOut,
    CitationOut,
    ClaimCreate,
    ClaimOut,
    ClaimPatch,
    InterviewOut,
    LibraryCreate,
    LibraryOut,
    LibraryPatch,
    QuestionCreate,
    SearchOut,
    SourceImportOut,
    SourceOut,
    SourcePatch,
    SourceTextOut,
    VoiceSampleIn,
)
from pbs_core.services import evidence, interview, knowledge, voice

router = APIRouter(prefix="/api", responses=ERRORS)
Q = Annotated[str, Query(min_length=1, max_length=500)]


# ---------- libraries ----------


@router.get("/knowledge/libraries", tags=["knowledge"])
def list_shared(ctx: Ctx) -> list[LibraryOut]:
    return knowledge.list_shared(ctx)


@router.post("/knowledge/libraries", tags=["knowledge"], status_code=status.HTTP_201_CREATED)
def create_shared(ctx: Ctx, body: LibraryCreate) -> LibraryOut:
    return knowledge.create_shared(ctx, body)


@router.patch("/knowledge/libraries/{library_id}", tags=["knowledge"])
def patch_library(ctx: Ctx, library_id: str, body: LibraryPatch) -> LibraryOut:
    return knowledge.patch_library(ctx, library_id, body)


@router.get("/knowledge/libraries/{library_id}/sources", tags=["knowledge"])
def library_sources(ctx: Ctx, library_id: str, include_removed: bool = False) -> list[SourceOut]:
    return knowledge.list_sources(ctx, library_id=library_id, include_removed=include_removed)


@router.post("/knowledge/libraries/{library_id}/sources", tags=["knowledge"], status_code=status.HTTP_201_CREATED)
async def import_to_library(
    ctx: Ctx,
    library_id: str,
    file: Annotated[UploadFile, File()],
    allow_duplicate: Annotated[bool, Form()] = False,
) -> SourceImportOut:
    data = await read_upload(file, ctx.settings.max_upload_mb)
    return knowledge.import_source(ctx, library_id, file.filename or "source", data, allow_duplicate=allow_duplicate)


@router.get("/knowledge/libraries/{library_id}/search", tags=["knowledge"])
def search_library(ctx: Ctx, library_id: str, q: Q, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> SearchOut:
    return knowledge.run_search(ctx, q, library_id=library_id, limit=limit)


# ---------- a book's knowledge ----------


@router.get("/projects/{project_id}/knowledge", tags=["knowledge"])
def book_knowledge(ctx: Ctx, project_id: str) -> BookKnowledgeOut:
    return knowledge.book_knowledge(ctx, project_id)


@router.put("/projects/{project_id}/knowledge/links/{library_id}", tags=["knowledge"])
def link_library(ctx: Ctx, project_id: str, library_id: str) -> BookKnowledgeOut:
    return knowledge.link(ctx, project_id, library_id, True)


@router.delete("/projects/{project_id}/knowledge/links/{library_id}", tags=["knowledge"])
def unlink_library(ctx: Ctx, project_id: str, library_id: str) -> BookKnowledgeOut:
    return knowledge.link(ctx, project_id, library_id, False)


@router.get("/projects/{project_id}/knowledge/sources", tags=["knowledge"])
def book_sources(ctx: Ctx, project_id: str, include_removed: bool = False) -> list[SourceOut]:
    return knowledge.list_sources(ctx, project_id=project_id, include_removed=include_removed)


@router.post("/projects/{project_id}/knowledge/sources", tags=["knowledge"], status_code=status.HTTP_201_CREATED)
async def import_to_book(
    ctx: Ctx,
    project_id: str,
    file: Annotated[UploadFile, File()],
    allow_duplicate: Annotated[bool, Form()] = False,
) -> SourceImportOut:
    data = await read_upload(file, ctx.settings.max_upload_mb)
    return knowledge.import_source(
        ctx, None, file.filename or "source", data, project_id=project_id, allow_duplicate=allow_duplicate
    )


@router.get("/projects/{project_id}/knowledge/search", tags=["knowledge"])
def search_book(ctx: Ctx, project_id: str, q: Q, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> SearchOut:
    return knowledge.run_search(ctx, q, project_id=project_id, limit=limit)


@router.get("/projects/{project_id}/citations", tags=["knowledge"])
def book_citations(ctx: Ctx, project_id: str) -> list[CitationOut]:
    return knowledge.citations(ctx, project_id)


# ---------- sources ----------


@router.get("/knowledge/sources/{source_id}", tags=["knowledge"])
def get_source(ctx: Ctx, source_id: str) -> SourceOut:
    return knowledge.get_source(ctx, source_id)


@router.patch("/knowledge/sources/{source_id}", tags=["knowledge"])
def patch_source(ctx: Ctx, source_id: str, body: SourcePatch) -> SourceOut:
    return knowledge.patch_source(ctx, source_id, body)


@router.delete("/knowledge/sources/{source_id}", tags=["knowledge"])
def remove_source(ctx: Ctx, source_id: str) -> SourceOut:
    return knowledge.remove_source(ctx, source_id)


@router.post("/knowledge/sources/{source_id}/reindex", tags=["knowledge"])
def reindex_source(ctx: Ctx, source_id: str) -> SourceOut:
    return knowledge.reindex_source(ctx, source_id)


@router.get("/knowledge/sources/{source_id}/text", tags=["knowledge"])
def source_text(ctx: Ctx, source_id: str) -> SourceTextOut:
    return knowledge.source_text(ctx, source_id)


# ---------- evidence ledger ----------


@router.get("/projects/{project_id}/claims", tags=["evidence"])
def list_claims(
    ctx: Ctx, project_id: str, include_proposed: bool = False, chapter_id: str | None = None
) -> list[ClaimOut]:
    return evidence.list_claims(ctx, project_id, include_proposed=include_proposed, chapter_id=chapter_id)


@router.post("/projects/{project_id}/claims", tags=["evidence"], status_code=status.HTTP_201_CREATED)
def create_claim(ctx: Ctx, project_id: str, body: ClaimCreate) -> ClaimOut:
    return evidence.create_claim(ctx, project_id, body)


@router.patch("/projects/{project_id}/claims/{claim_id}", tags=["evidence"])
def patch_claim(ctx: Ctx, project_id: str, claim_id: str, body: ClaimPatch) -> ClaimOut:
    return evidence.patch_claim(ctx, project_id, claim_id, body)


# ---------- author voice ----------


@router.get("/voice/profiles", tags=["voice"])
def list_profiles(ctx: Ctx) -> list[AuthorProfileOut]:
    return voice.list_profiles(ctx)


@router.post("/voice/profiles", tags=["voice"], status_code=status.HTTP_201_CREATED)
def create_profile(ctx: Ctx, body: AuthorProfileCreate) -> AuthorProfileOut:
    return voice.create_profile(ctx, body)


@router.get("/voice/profiles/{profile_id}", tags=["voice"])
def get_profile(ctx: Ctx, profile_id: str) -> AuthorProfileOut:
    return voice.get_profile(ctx, profile_id)


@router.patch("/voice/profiles/{profile_id}", tags=["voice"])
def patch_profile(ctx: Ctx, profile_id: str, body: AuthorProfilePatch) -> AuthorProfileOut:
    return voice.patch_profile(ctx, profile_id, body)


@router.post("/voice/profiles/{profile_id}/samples", tags=["voice"], status_code=status.HTTP_201_CREATED)
def add_sample(ctx: Ctx, profile_id: str, body: VoiceSampleIn) -> AuthorProfileOut:
    return voice.add_sample(ctx, profile_id, body)


@router.post("/voice/profiles/{profile_id}/samples/file", tags=["voice"], status_code=status.HTTP_201_CREATED)
async def add_sample_file(
    ctx: Ctx,
    profile_id: str,
    file: Annotated[UploadFile, File()],
    rights_confirmed: Annotated[bool, Form()] = False,
    rights_basis: Annotated[str, Form()] = "own_writing",
) -> AuthorProfileOut:
    data = await read_upload(file, ctx.settings.max_upload_mb)
    return voice.add_sample_file(
        ctx, profile_id, file.filename or "sample", data, rights_confirmed=rights_confirmed, rights_basis=rights_basis
    )


@router.delete("/voice/profiles/{profile_id}/samples/{sample_id}", tags=["voice"])
def remove_sample(ctx: Ctx, profile_id: str, sample_id: str) -> AuthorProfileOut:
    return voice.remove_sample(ctx, profile_id, sample_id)


# ---------- interview ----------


@router.get("/projects/{project_id}/interview", tags=["interview"])
def get_interview(ctx: Ctx, project_id: str) -> InterviewOut:
    return interview.get_interview(ctx, project_id)


@router.post("/projects/{project_id}/interview/questions", tags=["interview"], status_code=status.HTTP_201_CREATED)
def add_question(ctx: Ctx, project_id: str, body: QuestionCreate) -> InterviewOut:
    return interview.add_question(ctx, project_id, body)


@router.put("/projects/{project_id}/interview/questions/{question_id}/answer", tags=["interview"])
def answer(ctx: Ctx, project_id: str, question_id: str, body: AnswerIn) -> InterviewOut:
    return interview.answer(ctx, project_id, question_id, body)
