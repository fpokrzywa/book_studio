"""HTTP routes for planning: New Book wizard, brief, research, outlines and generation runs (Phase 05)."""

from __future__ import annotations

from fastapi import APIRouter, status

from pbs_core.api.routes import ERRORS, Ctx
from pbs_core.contracts_ai import JobOut
from pbs_core.contracts_planning import (
    ApplyOut,
    BriefIn,
    BriefOut,
    FindingIn,
    FindingOut,
    FindingPatch,
    NewBookIn,
    NewBookOut,
    OutlineDraftIn,
    OutlineGenerateIn,
    OutlineOut,
    PlanEstimateOut,
    PlanRequestIn,
    ResearchIdeasIn,
    ResearchProviderOut,
    ResearchProvidersIn,
    ResearchSearchIn,
    ResearchSearchOut,
    RunOut,
    SaveHitIn,
)
from pbs_core.services import planning

router = APIRouter(prefix="/api", responses=ERRORS)


@router.post("/books", tags=["planning"], status_code=status.HTTP_201_CREATED)
def new_book(ctx: Ctx, body: NewBookIn) -> NewBookOut:
    return planning.new_book(ctx, body)


@router.get("/projects/{project_id}/brief", tags=["planning"])
def get_brief(ctx: Ctx, project_id: str) -> BriefOut:
    return planning.get_brief(ctx, project_id)


@router.put("/projects/{project_id}/brief", tags=["planning"])
def put_brief(ctx: Ctx, project_id: str, body: BriefIn) -> BriefOut:
    return planning.put_brief(ctx, project_id, body)


@router.post("/projects/{project_id}/brief/approve", tags=["planning"])
def approve_brief(ctx: Ctx, project_id: str) -> BriefOut:
    return planning.approve_brief(ctx, project_id)


# ---------- research ----------


@router.get("/research/providers", tags=["planning"])
def research_providers(ctx: Ctx) -> list[ResearchProviderOut]:
    return planning.list_providers(ctx)


@router.put("/research/providers", tags=["planning"])
def set_research_providers(ctx: Ctx, body: ResearchProvidersIn) -> list[ResearchProviderOut]:
    return planning.set_providers(ctx, body)


@router.get("/projects/{project_id}/research/findings", tags=["planning"])
def list_findings(ctx: Ctx, project_id: str, include_archived: bool = False) -> list[FindingOut]:
    return planning.list_findings(ctx, project_id, include_archived)


@router.post("/projects/{project_id}/research/findings", tags=["planning"], status_code=status.HTTP_201_CREATED)
def add_finding(ctx: Ctx, project_id: str, body: FindingIn) -> FindingOut:
    return planning.add_finding(ctx, project_id, body)


@router.patch("/projects/{project_id}/research/findings/{finding_id}", tags=["planning"])
def patch_finding(ctx: Ctx, project_id: str, finding_id: str, body: FindingPatch) -> FindingOut:
    return planning.patch_finding(ctx, project_id, finding_id, body)


@router.post("/projects/{project_id}/research/search", tags=["planning"])
def research_search(ctx: Ctx, project_id: str, body: ResearchSearchIn) -> ResearchSearchOut:
    return planning.search(ctx, project_id, body)


@router.post("/projects/{project_id}/research/save", tags=["planning"], status_code=status.HTTP_201_CREATED)
def save_hit(ctx: Ctx, project_id: str, body: SaveHitIn) -> FindingOut:
    return planning.save_hit(ctx, project_id, body)


@router.post("/projects/{project_id}/research/ideas", tags=["planning"], status_code=status.HTTP_202_ACCEPTED)
def research_ideas(ctx: Ctx, project_id: str, body: ResearchIdeasIn) -> JobOut:
    return planning.research_ideas(ctx, project_id, body)


# ---------- outlines ----------


@router.get("/projects/{project_id}/outlines", tags=["planning"])
def list_outlines(ctx: Ctx, project_id: str) -> list[OutlineOut]:
    return planning.list_outlines(ctx, project_id)


@router.put("/projects/{project_id}/outlines/draft", tags=["planning"])
def save_draft(ctx: Ctx, project_id: str, body: OutlineDraftIn) -> OutlineOut:
    return planning.save_draft(ctx, project_id, body)


@router.post("/projects/{project_id}/outlines/generate", tags=["planning"], status_code=status.HTTP_202_ACCEPTED)
def generate_outline(ctx: Ctx, project_id: str, body: OutlineGenerateIn) -> JobOut:
    return planning.generate_outline(ctx, project_id, body)


@router.post("/projects/{project_id}/outlines/{outline_id}/edit", tags=["planning"])
def edit_outline(ctx: Ctx, project_id: str, outline_id: str) -> OutlineOut:
    return planning.edit_version(ctx, project_id, outline_id)


@router.post("/projects/{project_id}/outlines/{outline_id}/approve", tags=["planning"])
def approve_outline(ctx: Ctx, project_id: str, outline_id: str) -> OutlineOut:
    return planning.approve_outline(ctx, project_id, outline_id)


@router.post("/projects/{project_id}/outlines/{outline_id}/reject", tags=["planning"])
def reject_outline(ctx: Ctx, project_id: str, outline_id: str) -> OutlineOut:
    return planning.reject_outline(ctx, project_id, outline_id)


@router.post("/projects/{project_id}/outlines/{outline_id}/apply", tags=["planning"])
def apply_outline(ctx: Ctx, project_id: str, outline_id: str) -> ApplyOut:
    return planning.apply_outline(ctx, project_id, outline_id)


# ---------- generation runs ----------


@router.post("/projects/{project_id}/runs/estimate", tags=["planning"])
def estimate_run(ctx: Ctx, project_id: str, body: PlanRequestIn) -> PlanEstimateOut:
    return planning.estimate_run(ctx, project_id, body)


@router.post("/projects/{project_id}/runs", tags=["planning"], status_code=status.HTTP_202_ACCEPTED)
def start_run(ctx: Ctx, project_id: str, body: PlanRequestIn) -> RunOut:
    return planning.start_run(ctx, project_id, body)


@router.get("/projects/{project_id}/runs", tags=["planning"])
def list_runs(ctx: Ctx, project_id: str) -> list[RunOut]:
    return planning.list_runs(ctx, project_id)


@router.post("/projects/{project_id}/runs/{run_id}/stop", tags=["planning"])
def stop_run(ctx: Ctx, project_id: str, run_id: str) -> RunOut:
    return planning.stop_run(ctx, project_id, run_id)
