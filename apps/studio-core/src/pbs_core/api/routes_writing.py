"""HTTP routes for the writing pipeline, continuity memory, quality reviews and originality (Phase 06)."""

from __future__ import annotations

from fastapi import APIRouter, status

from pbs_core.api.routes import ERRORS, Ctx
from pbs_core.contracts_ai import JobOut
from pbs_core.contracts_writing import (
    AiReviewIn,
    FactIn,
    FactOut,
    FactPatch,
    FindingPatchIn,
    JobHistoryOut,
    OriginalityOut,
    PlanOut,
    QualityFindingOut,
    QualityRunIn,
    QualityRunOut,
    SectionApproveIn,
    SummaryIn,
    SummaryOut,
    WritingSettingsIn,
    WritingSettingsOut,
)
from pbs_core.services import writing

router = APIRouter(prefix="/api/projects/{project_id}/writing", responses=ERRORS, tags=["writing"])


@router.get("/plans")
def list_plans(ctx: Ctx, project_id: str, chapter_id: str | None = None) -> list[PlanOut]:
    return writing.list_plans(ctx, project_id, chapter_id)


@router.get("/plans/{plan_id}")
def get_plan(ctx: Ctx, project_id: str, plan_id: str) -> PlanOut:
    return writing.get_plan(ctx, project_id, plan_id)


@router.get("/plans/{plan_id}/history")
def plan_history(ctx: Ctx, project_id: str, plan_id: str) -> list[JobHistoryOut]:
    return writing.plan_history(ctx, project_id, plan_id)


@router.post("/plans/{plan_id}/pause")
def pause_plan(ctx: Ctx, project_id: str, plan_id: str) -> PlanOut:
    return writing.pause_plan(ctx, project_id, plan_id)


@router.post("/plans/{plan_id}/resume")
def resume_plan(ctx: Ctx, project_id: str, plan_id: str) -> PlanOut:
    return writing.resume_plan(ctx, project_id, plan_id)


@router.post("/plans/{plan_id}/cancel")
def cancel_plan(ctx: Ctx, project_id: str, plan_id: str) -> PlanOut:
    return writing.cancel_plan(ctx, project_id, plan_id)


@router.post("/plans/{plan_id}/sections/{section_id}/retry")
def retry_section(ctx: Ctx, project_id: str, plan_id: str, section_id: str) -> PlanOut:
    return writing.retry_section(ctx, project_id, plan_id, section_id)


@router.post("/plans/{plan_id}/sections/{section_id}/approve")
def approve_section(ctx: Ctx, project_id: str, plan_id: str, section_id: str, body: SectionApproveIn) -> PlanOut:
    return writing.approve_section(ctx, project_id, plan_id, section_id, body)


@router.get("/facts")
def list_facts(ctx: Ctx, project_id: str) -> list[FactOut]:
    return writing.list_facts(ctx, project_id)


@router.post("/facts", status_code=status.HTTP_201_CREATED)
def add_fact(ctx: Ctx, project_id: str, body: FactIn) -> FactOut:
    return writing.add_fact(ctx, project_id, body)


@router.patch("/facts/{fact_id}")
def patch_fact(ctx: Ctx, project_id: str, fact_id: str, body: FactPatch) -> FactOut:
    return writing.patch_fact(ctx, project_id, fact_id, body)


@router.get("/summaries")
def list_summaries(ctx: Ctx, project_id: str) -> list[SummaryOut]:
    return writing.list_summaries(ctx, project_id)


@router.put("/summaries/{chapter_id}")
def put_summary(ctx: Ctx, project_id: str, chapter_id: str, body: SummaryIn) -> SummaryOut:
    return writing.put_summary(ctx, project_id, chapter_id, body)


@router.get("/settings")
def get_settings(ctx: Ctx, project_id: str) -> WritingSettingsOut:
    return writing.get_settings(ctx, project_id)


@router.put("/settings")
def put_settings(ctx: Ctx, project_id: str, body: WritingSettingsIn) -> WritingSettingsOut:
    return writing.put_settings(ctx, project_id, body)


@router.get("/quality")
def list_findings(ctx: Ctx, project_id: str, chapter_id: str | None = None) -> list[QualityFindingOut]:
    return writing.list_findings(ctx, project_id, chapter_id)


@router.post("/quality/run")
def run_quality(ctx: Ctx, project_id: str, body: QualityRunIn) -> QualityRunOut:
    return writing.run_quality(ctx, project_id, body)


@router.patch("/quality/{finding_id}")
def patch_finding(ctx: Ctx, project_id: str, finding_id: str, body: FindingPatchIn) -> QualityFindingOut:
    return writing.patch_finding(ctx, project_id, finding_id, body)


@router.post("/quality/ai-review", status_code=status.HTTP_202_ACCEPTED)
def ai_review(ctx: Ctx, project_id: str, body: AiReviewIn) -> JobOut:
    return writing.ai_review(ctx, project_id, body)


@router.get("/originality")
def originality(ctx: Ctx, project_id: str) -> OriginalityOut:
    return writing.originality_report(ctx, project_id)
