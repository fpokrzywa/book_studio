"""HTTP routes for AI settings, jobs, proposals and usage. Thin: validate -> service -> contract."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from pbs_core.api.routes import ERRORS, Ctx
from pbs_core.contracts_ai import (
    AcceptIn,
    AcceptOut,
    AiRequestIn,
    AiStatusOut,
    AiTask,
    ConsentOut,
    EstimateOut,
    HealthOut,
    JobLogOut,
    JobOut,
    JobStatus,
    KeyIn,
    ManualModelIn,
    PriceIn,
    PriceOut,
    PrivacyIn,
    ProposalOut,
    ProposalStatus,
    ProviderCreate,
    ProviderKindOut,
    ProviderOut,
    ProviderPatch,
    RouteIn,
    RouteOut,
    UsageOut,
)
from pbs_core.services import ai

router = APIRouter(prefix="/api", responses=ERRORS)


@router.get("/ai/status", tags=["ai"])
def ai_status(ctx: Ctx) -> AiStatusOut:
    return ai.status(ctx)


@router.put("/ai/privacy", tags=["ai"])
def set_privacy(ctx: Ctx, body: PrivacyIn) -> AiStatusOut:
    return ai.set_privacy(ctx, body)


@router.get("/ai/provider-kinds", tags=["ai"])
def provider_kinds(ctx: Ctx) -> list[ProviderKindOut]:
    return ai.provider_kinds(ctx)


@router.get("/ai/providers", tags=["ai"])
def list_providers(ctx: Ctx) -> list[ProviderOut]:
    return ai.list_providers(ctx)


@router.post("/ai/providers", tags=["ai"], status_code=status.HTTP_201_CREATED)
def create_provider(ctx: Ctx, body: ProviderCreate) -> ProviderOut:
    return ai.create_provider(ctx, body)


@router.get("/ai/providers/{provider_id}", tags=["ai"])
def get_provider(ctx: Ctx, provider_id: str) -> ProviderOut:
    return ai.get_provider(ctx, provider_id)


@router.patch("/ai/providers/{provider_id}", tags=["ai"])
def update_provider(ctx: Ctx, provider_id: str, body: ProviderPatch) -> ProviderOut:
    return ai.update_provider(ctx, provider_id, body)


@router.delete("/ai/providers/{provider_id}", tags=["ai"], status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(ctx: Ctx, provider_id: str) -> None:
    ai.delete_provider(ctx, provider_id)


@router.put("/ai/providers/{provider_id}/key", tags=["ai"])
def set_key(ctx: Ctx, provider_id: str, body: KeyIn) -> ProviderOut:
    return ai.set_key(ctx, provider_id, body.api_key.get_secret_value())


@router.delete("/ai/providers/{provider_id}/key", tags=["ai"])
def delete_key(ctx: Ctx, provider_id: str) -> ProviderOut:
    return ai.delete_key(ctx, provider_id)


@router.post("/ai/providers/{provider_id}/test", tags=["ai"])
def test_provider(ctx: Ctx, provider_id: str) -> HealthOut:
    return ai.test_provider(ctx, provider_id)


@router.post("/ai/providers/{provider_id}/models/refresh", tags=["ai"])
def refresh_models(ctx: Ctx, provider_id: str) -> ProviderOut:
    return ai.refresh_models(ctx, provider_id)


@router.put("/ai/providers/{provider_id}/models", tags=["ai"])
def put_model(ctx: Ctx, provider_id: str, body: ManualModelIn) -> ProviderOut:
    return ai.put_manual_model(ctx, provider_id, body)


@router.delete("/ai/providers/{provider_id}/models", tags=["ai"])
def delete_model(ctx: Ctx, provider_id: str, name: Annotated[str, Query(max_length=200)]) -> ProviderOut:
    return ai.delete_model(ctx, provider_id, name)


@router.get("/ai/providers/{provider_id}/prices", tags=["ai"])
def list_prices(ctx: Ctx, provider_id: str) -> list[PriceOut]:
    return ai.list_prices(ctx, provider_id)


@router.put("/ai/providers/{provider_id}/prices", tags=["ai"])
def put_price(ctx: Ctx, provider_id: str, body: PriceIn) -> PriceOut:
    return ai.put_price(ctx, provider_id, body)


@router.delete("/ai/providers/{provider_id}/prices/{price_id}", tags=["ai"], status_code=status.HTTP_204_NO_CONTENT)
def delete_price(ctx: Ctx, provider_id: str, price_id: str) -> None:
    ai.delete_price(ctx, provider_id, price_id)


@router.get("/ai/routes", tags=["ai"])
def list_routes(ctx: Ctx) -> list[RouteOut]:
    return ai.list_routes(ctx)


@router.put("/ai/routes/{task}", tags=["ai"])
def put_route(ctx: Ctx, task: AiTask, body: RouteIn) -> RouteOut:
    return ai.put_route(ctx, task, body)


@router.delete("/ai/routes/{task}", tags=["ai"], status_code=status.HTTP_204_NO_CONTENT)
def delete_route(ctx: Ctx, task: AiTask) -> None:
    ai.delete_route(ctx, task)


@router.get("/projects/{project_id}/ai/consent", tags=["ai"])
def list_consent(ctx: Ctx, project_id: str) -> list[ConsentOut]:
    return ai.list_consent(ctx, project_id)


@router.put("/projects/{project_id}/ai/consent/{provider_id}", tags=["ai"])
def grant_consent(ctx: Ctx, project_id: str, provider_id: str) -> ConsentOut:
    return ai.grant_consent(ctx, project_id, provider_id)


@router.delete("/projects/{project_id}/ai/consent/{provider_id}", tags=["ai"], status_code=status.HTTP_204_NO_CONTENT)
def revoke_consent(ctx: Ctx, project_id: str, provider_id: str) -> None:
    ai.revoke_consent(ctx, project_id, provider_id)


@router.post("/projects/{project_id}/ai/estimate", tags=["ai"])
def estimate(ctx: Ctx, project_id: str, body: AiRequestIn) -> EstimateOut:
    return ai.estimate(ctx, project_id, body)


@router.post("/projects/{project_id}/ai/jobs", tags=["ai"], status_code=status.HTTP_202_ACCEPTED)
def enqueue(ctx: Ctx, project_id: str, body: AiRequestIn) -> JobOut:
    return ai.enqueue(ctx, project_id, body)


@router.get("/ai/jobs", tags=["ai"])
def list_jobs(
    ctx: Ctx,
    project_id: str | None = None,
    chapter_id: str | None = None,
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[JobOut]:
    return ai.list_jobs(ctx, project_id=project_id, chapter_id=chapter_id, status=status_filter, limit=limit)


@router.get("/ai/jobs/{job_id}", tags=["ai"])
def get_job(ctx: Ctx, job_id: str) -> JobOut:
    return ai.get_job(ctx, job_id)


@router.get("/ai/jobs/{job_id}/logs", tags=["ai"])
def job_logs(ctx: Ctx, job_id: str) -> list[JobLogOut]:
    return ai.job_logs(ctx, job_id)


@router.post("/ai/jobs/{job_id}/cancel", tags=["ai"])
def cancel_job(ctx: Ctx, job_id: str) -> JobOut:
    return ai.cancel_job(ctx, job_id)


@router.post("/ai/jobs/{job_id}/retry", tags=["ai"])
def retry_job(ctx: Ctx, job_id: str) -> JobOut:
    return ai.retry_job(ctx, job_id)


@router.get("/projects/{project_id}/proposals", tags=["ai"])
def list_proposals(
    ctx: Ctx,
    project_id: str,
    chapter_id: str | None = None,
    status_filter: Annotated[ProposalStatus | None, Query(alias="status")] = None,
) -> list[ProposalOut]:
    return ai.list_proposals(ctx, project_id, chapter_id=chapter_id, status=status_filter)


@router.get("/projects/{project_id}/proposals/{proposal_id}", tags=["ai"])
def get_proposal(ctx: Ctx, project_id: str, proposal_id: str) -> ProposalOut:
    return ai.get_proposal(ctx, project_id, proposal_id)


@router.post("/projects/{project_id}/proposals/{proposal_id}/accept", tags=["ai"])
def accept_proposal(ctx: Ctx, project_id: str, proposal_id: str, body: AcceptIn) -> AcceptOut:
    return ai.accept_proposal(ctx, project_id, proposal_id, body)


@router.post("/projects/{project_id}/proposals/{proposal_id}/reject", tags=["ai"])
def reject_proposal(ctx: Ctx, project_id: str, proposal_id: str) -> ProposalOut:
    return ai.reject_proposal(ctx, project_id, proposal_id)


@router.get("/ai/usage", tags=["ai"])
def usage(ctx: Ctx, project_id: str | None = None, limit: Annotated[int, Query(ge=1, le=1000)] = 200) -> UsageOut:
    return ai.usage(ctx, project_id=project_id, limit=limit)
