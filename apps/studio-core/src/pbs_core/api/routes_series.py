"""HTTP routes for series: books, the shared story bible (canon) and continuity review (Phase 08)."""

from __future__ import annotations

from fastapi import APIRouter, status

from pbs_core.api.routes import ERRORS, Ctx
from pbs_core.contracts_advanced import (
    CanonFactIn,
    CanonFactOut,
    CanonFactPatch,
    CanonOut,
    EntityIn,
    EntityOut,
    EntityPatch,
    ImportNotesOut,
    IssueOut,
    RelationshipIn,
    RelationshipOut,
    RelationshipPatch,
    ResolveIn,
    ReviewIn,
    ReviewOut,
    SeriesBookIn,
    SeriesIn,
    SeriesOut,
)
from pbs_core.services import series

router = APIRouter(prefix="/api/series", responses=ERRORS, tags=["series"])


@router.get("")
def list_series(ctx: Ctx) -> list[SeriesOut]:
    return series.list_series(ctx)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_series(ctx: Ctx, body: SeriesIn) -> SeriesOut:
    return series.create_series(ctx, body)


@router.get("/{series_id}")
def get_series(ctx: Ctx, series_id: str) -> SeriesOut:
    return series.get_series(ctx, series_id)


@router.post("/{series_id}/books")
def add_book(ctx: Ctx, series_id: str, body: SeriesBookIn) -> SeriesOut:
    return series.add_book(ctx, series_id, body)


@router.delete("/{series_id}/books/{project_id}")
def remove_book(ctx: Ctx, series_id: str, project_id: str) -> SeriesOut:
    return series.remove_book(ctx, series_id, project_id)


@router.get("/{series_id}/canon")
def canon(ctx: Ctx, series_id: str) -> CanonOut:
    return series.canon(ctx, series_id)


@router.post("/{series_id}/entities", status_code=status.HTTP_201_CREATED)
def add_entity(ctx: Ctx, series_id: str, body: EntityIn) -> EntityOut:
    return series.add_entity(ctx, series_id, body)


@router.patch("/{series_id}/entities/{entity_id}")
def patch_entity(ctx: Ctx, series_id: str, entity_id: str, body: EntityPatch) -> EntityOut:
    return series.patch_entity(ctx, series_id, entity_id, body)


@router.post("/{series_id}/facts", status_code=status.HTTP_201_CREATED)
def add_fact(ctx: Ctx, series_id: str, body: CanonFactIn) -> CanonFactOut:
    return series.add_fact(ctx, series_id, body)


@router.patch("/{series_id}/facts/{fact_id}")
def patch_fact(ctx: Ctx, series_id: str, fact_id: str, body: CanonFactPatch) -> CanonFactOut:
    return series.patch_fact(ctx, series_id, fact_id, body)


@router.post("/{series_id}/relationships", status_code=status.HTTP_201_CREATED)
def add_relationship(ctx: Ctx, series_id: str, body: RelationshipIn) -> RelationshipOut:
    return series.add_relationship(ctx, series_id, body)


@router.patch("/{series_id}/relationships/{rel_id}")
def patch_relationship(ctx: Ctx, series_id: str, rel_id: str, body: RelationshipPatch) -> RelationshipOut:
    return series.patch_relationship(ctx, series_id, rel_id, body)


@router.post("/{series_id}/import-notes/{project_id}")
def import_notes(ctx: Ctx, series_id: str, project_id: str) -> ImportNotesOut:
    return series.import_book_notes(ctx, series_id, project_id)


@router.get("/{series_id}/issues")
def list_issues(ctx: Ctx, series_id: str) -> list[IssueOut]:
    return series.list_issues(ctx, series_id)


@router.post("/{series_id}/review")
def review(ctx: Ctx, series_id: str, body: ReviewIn) -> ReviewOut:
    return series.review(ctx, series_id, body)


@router.post("/{series_id}/issues/{issue_id}/resolve")
def resolve(ctx: Ctx, series_id: str, issue_id: str, body: ResolveIn) -> IssueOut:
    return series.resolve(ctx, series_id, issue_id, body)
