"""Phase 03: AI jobs end to end with the deterministic test model (no network)."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from pbs_core.context import AppContext, build_context
from pbs_core.jobs.runner import JobRunner
from pbs_core.providers.egress import external_requests
from pbs_core.storage.ai_models import Job, Proposal, UsageRecord
from pbs_core.storage.models import ChapterRevision
from tests.conftest import make_settings, new_chapter, new_project, save

OPENING = "The engine room was quiet.\n"


def mock_provider(client: TestClient) -> dict[str, Any]:
    r = client.post("/api/ai/providers", json={"kind": "mock"})
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def book(client: TestClient, text_md: str = OPENING) -> tuple[str, str]:
    p = new_project(client)
    c = new_chapter(client, p["id"])
    assert save(client, p["id"], c["id"], text_md, 0).status_code == 200
    return p["id"], c["id"]


def ask(client: TestClient, pid: str, cid: str, provider_id: str, **kw: Any) -> Any:
    body: dict[str, Any] = {
        "chapter_id": cid,
        "task": "draft",
        "instruction": "Write one paragraph about the night shift.",
        "mode": "append",
        "base_revision_no": 1,
        "provider_id": provider_id,
        "model_name": "mock-writer",
        "client_request_id": uuid.uuid4().hex,
    }
    body.update(kw)
    return client.post(f"/api/projects/{pid}/ai/jobs", json=body)


def job(client: TestClient, job_id: str) -> dict[str, Any]:
    r = client.get(f"/api/ai/jobs/{job_id}")
    assert r.status_code == 200
    return r.json()  # type: ignore[no-any-return]


@pytest.fixture
def runner(ctx: AppContext) -> JobRunner:
    r = JobRunner(ctx, workers=1)
    ctx.jobs = r
    return r


def test_draft_into_review_then_accept_creates_one_ai_revision(
    client: TestClient, ctx: AppContext, runner: JobRunner
) -> None:
    before = external_requests()  # process-wide counter: compare, don't assume empty
    prov = mock_provider(client)
    pid, cid = book(client)
    r = ask(client, pid, cid, prov["id"])
    assert r.status_code == 202, r.text
    j = r.json()
    assert j["status"] == "queued" and j["provider_local"] is True

    assert runner.run_until_idle() == 1
    j = job(client, j["id"])
    assert j["status"] == "succeeded" and j["stage"] == "ready_for_review" and j["proposal_id"]

    # Nothing is applied until the author accepts.
    content = client.get(f"/api/projects/{pid}/chapters/{cid}/content").json()
    assert content["revision_no"] == 1 and content["source_md"] == OPENING

    props = client.get(f"/api/projects/{pid}/proposals", params={"chapter_id": cid, "status": "pending"}).json()
    assert len(props) == 1 and props[0]["applicable"] is True
    prop = props[0]
    assert prop["payload_md"].startswith("[Test model output, not AI]")
    assert prop["provenance"]["model"] == "mock-writer" and prop["provenance"]["task"] == "draft"

    acc = client.post(f"/api/projects/{pid}/proposals/{prop['id']}/accept", json={"expected_head_no": 1})
    assert acc.status_code == 200, acc.text
    saved = acc.json()["save"]["content"]
    assert saved["revision_no"] == 2
    assert saved["source_md"].startswith(OPENING.strip()) and prop["payload_md"] in saved["source_md"]
    revs = client.get(f"/api/projects/{pid}/chapters/{cid}/revisions").json()
    assert revs[0]["revision_no"] == 2 and revs[0]["origin"] == "ai_generated"

    # A second accept (double click, retry, another tab) never applies it twice.
    again = client.post(f"/api/projects/{pid}/proposals/{prop['id']}/accept", json={"expected_head_no": 2})
    assert again.status_code == 409 and again.json()["reason"] == "already_applied"
    assert client.get(f"/api/projects/{pid}/chapters/{cid}/content").json()["revision_no"] == 2

    usage = client.get("/api/ai/usage", params={"project_id": pid}).json()
    assert len(usage["rows"]) == 1 and usage["rows"][0]["cost_amount"] == "0"
    assert external_requests() == before


def test_edited_accept_is_ai_assisted_and_reject_leaves_chapter(client: TestClient, runner: JobRunner) -> None:
    prov = mock_provider(client)
    pid, cid = book(client)
    ask(client, pid, cid, prov["id"])
    ask(client, pid, cid, prov["id"])
    runner.run_until_idle()
    a, b = client.get(f"/api/projects/{pid}/proposals").json()
    assert client.post(f"/api/projects/{pid}/proposals/{a['id']}/reject").json()["status"] == "rejected"
    acc = client.post(
        f"/api/projects/{pid}/proposals/{b['id']}/accept", json={"expected_head_no": 1, "edited_md": "My own take."}
    )
    assert acc.status_code == 200
    assert acc.json()["save"]["content"]["source_md"].endswith("My own take.\n")
    assert client.get(f"/api/projects/{pid}/chapters/{cid}/revisions").json()[0]["origin"] == "ai_assisted"


def test_same_request_twice_creates_one_job(client: TestClient, ctx: AppContext) -> None:
    prov = mock_provider(client)
    pid, cid = book(client)
    rid = uuid.uuid4().hex
    one = ask(client, pid, cid, prov["id"], client_request_id=rid).json()
    two = ask(client, pid, cid, prov["id"], client_request_id=rid).json()
    assert one["id"] == two["id"]
    with ctx.db.tx() as s:
        assert len(s.scalars(select(Job)).all()) == 1


def test_database_refuses_applying_a_proposal_twice(client: TestClient, ctx: AppContext, runner: JobRunner) -> None:
    prov = mock_provider(client)
    pid, cid = book(client)
    ask(client, pid, cid, prov["id"])
    runner.run_until_idle()
    prop = client.get(f"/api/projects/{pid}/proposals").json()[0]
    client.post(f"/api/projects/{pid}/proposals/{prop['id']}/accept", json={"expected_head_no": 1})
    with pytest.raises(IntegrityError), ctx.db.tx() as s:
        rev = s.scalars(select(ChapterRevision).where(ChapterRevision.accepted_proposal_id == prop["id"])).one()
        s.execute(
            text(
                "INSERT INTO chapter_revision (id, project_id, chapter_id, revision_no, origin, source_md, bdm_json,"
                " parser_version, content_hash, word_count, accepted_proposal_id, created_at)"
                " VALUES (:id, :p, :c, 99, 'ai_generated', 'x', '{}', 'v', 'h', 1, :a, 'now')"
            ),
            {"id": ctx.ids.new(), "p": rev.project_id, "c": rev.chapter_id, "a": prop["id"]},
        )


def test_unsaved_changes_block_requests_and_accepts(client: TestClient, runner: JobRunner) -> None:
    prov = mock_provider(client)
    pid, cid = book(client)
    ask(client, pid, cid, prov["id"])
    runner.run_until_idle()
    prop = client.get(f"/api/projects/{pid}/proposals").json()[0]
    client.put(f"/api/projects/{pid}/chapters/{cid}/draft", json={"source_md": "typing...", "base_revision_no": 1})
    r = ask(client, pid, cid, prov["id"])
    assert r.status_code == 409 and r.json()["reason"] == "unsaved_changes"
    a = client.post(f"/api/projects/{pid}/proposals/{prop['id']}/accept", json={"expected_head_no": 1})
    assert a.status_code == 409 and a.json()["reason"] == "unsaved_changes"
    # The draft survived.
    assert client.get(f"/api/projects/{pid}/chapters/{cid}/content").json()["draft"]["source_md"] == "typing..."


def test_replace_selection_goes_stale_when_passage_changes(client: TestClient, runner: JobRunner) -> None:
    prov = mock_provider(client)
    pid, cid = book(client, "Alpha beta gamma.\n")
    r = ask(client, pid, cid, prov["id"], task="revise", mode="replace_selection", selection_start=6, selection_end=10)
    assert r.status_code == 202, r.text
    runner.run_until_idle()
    prop = client.get(f"/api/projects/{pid}/proposals").json()[0]
    assert prop["original_text"] == "beta" and prop["applicable"]
    assert save(client, pid, cid, "Alpha delta gamma.\n", 1).status_code == 200
    prop = client.get(f"/api/projects/{pid}/proposals/{prop['id']}").json()
    assert prop["applicable"] is False
    a = client.post(f"/api/projects/{pid}/proposals/{prop['id']}/accept", json={"expected_head_no": 2})
    assert a.status_code == 409 and a.json()["reason"] == "not_applicable"


def test_replace_selection_applies_in_place(client: TestClient, runner: JobRunner) -> None:
    prov = mock_provider(client)
    pid, cid = book(client, "Alpha beta gamma.\n")
    ask(client, pid, cid, prov["id"], task="revise", mode="replace_selection", selection_start=6, selection_end=10)
    runner.run_until_idle()
    prop = client.get(f"/api/projects/{pid}/proposals").json()[0]
    a = client.post(
        f"/api/projects/{pid}/proposals/{prop['id']}/accept", json={"expected_head_no": 1, "edited_md": "BETA"}
    )
    assert a.json()["save"]["content"]["source_md"] == "Alpha BETA gamma.\n"


def test_cancel_queued_job(client: TestClient, runner: JobRunner) -> None:
    prov = mock_provider(client)
    pid, cid = book(client)
    j = ask(client, pid, cid, prov["id"]).json()
    c = client.post(f"/api/ai/jobs/{j['id']}/cancel")
    assert c.json()["status"] == "cancelled"
    assert runner.run_until_idle() == 0
    assert client.get(f"/api/projects/{pid}/proposals").json() == []


def test_cancel_while_streaming_applies_nothing(client: TestClient, runner: JobRunner) -> None:
    prov = mock_provider(client)
    pid, cid = book(client)
    j = ask(client, pid, cid, prov["id"], instruction="[[mock:slow]] keep going").json()
    t = threading.Thread(target=runner.run_once)
    t.start()
    deadline = time.monotonic() + 10
    while job(client, j["id"])["stage"] != "receiving" and time.monotonic() < deadline:
        time.sleep(0.1)
    assert job(client, j["id"])["stage"] == "receiving"
    assert client.post(f"/api/ai/jobs/{j['id']}/cancel").status_code == 200
    t.join(timeout=10)
    done = job(client, j["id"])
    assert done["status"] == "cancelled" and done["partial_output"]
    assert client.get(f"/api/projects/{pid}/proposals").json() == []
    assert client.get(f"/api/projects/{pid}/chapters/{cid}/content").json()["revision_no"] == 1
    # Cancelled work can be retried and then completes normally.
    assert client.post(f"/api/ai/jobs/{j['id']}/retry").json()["status"] == "queued"


def test_rate_limit_is_retried_with_backoff(client: TestClient, ctx: AppContext, runner: JobRunner) -> None:
    prov = mock_provider(client)
    pid, cid = book(client)
    j = ask(client, pid, cid, prov["id"], instruction="[[mock:rate_limit]] once").json()
    runner.run_once()
    after1 = job(client, j["id"])
    assert (
        after1["status"] == "queued"
        and after1["stage"] == "waiting_to_retry"
        and after1["error_code"] == "rate_limited"
    )
    time.sleep(0.15)
    runner.run_until_idle()
    done = job(client, j["id"])
    assert done["status"] == "succeeded" and done["attempt"] == 2
    logs = [x["message"] for x in client.get(f"/api/ai/jobs/{j['id']}/logs").json()]
    assert any("Retrying" in m for m in logs)
    with ctx.db.tx() as s:
        assert len(s.scalars(select(UsageRecord)).all()) == 1
        assert len(s.scalars(select(Proposal)).all()) == 1


def test_auth_error_fails_without_retry_then_manual_retry(client: TestClient, runner: JobRunner) -> None:
    prov = mock_provider(client)
    pid, cid = book(client)
    j = ask(client, pid, cid, prov["id"], instruction="[[mock:auth]]").json()
    runner.run_until_idle()
    failed = job(client, j["id"])
    assert failed["status"] == "failed" and failed["error_code"] == "auth" and failed["attempt"] == 1
    assert "API key" in failed["error_message"]
    retried = client.post(f"/api/ai/jobs/{j['id']}/retry").json()
    assert retried["status"] == "queued" and retried["max_attempts"] == 4
    runner.run_until_idle()
    assert job(client, j["id"])["attempt"] == 2


def test_structured_brainstorm_is_validated(client: TestClient, runner: JobRunner) -> None:
    prov = mock_provider(client)
    pid, cid = book(client)
    j = ask(client, pid, cid, prov["id"], task="brainstorm", mode="append").json()
    runner.run_until_idle()
    prop = client.get(f"/api/projects/{pid}/proposals").json()[0]
    assert prop["mode"] == "note" and prop["applicable"] is False
    assert prop["payload_md"].startswith("- **Idea 1**")
    assert job(client, j["id"])["status"] == "succeeded"

    bad = ask(client, pid, cid, prov["id"], task="brainstorm", instruction="[[mock:bad_json]]").json()
    for _ in range(3):
        runner.run_once()
        time.sleep(0.01)
        with runner.ctx.db.tx() as s:
            row = s.get(Job, bad["id"])
            assert row is not None
            row.run_after = runner.ctx.clock.iso()  # skip the backoff wait
    runner.run_until_idle()
    out = job(client, bad["id"])
    assert out["status"] == "failed" and out["error_code"] == "invalid_output" and out["attempt"] == 3


def test_restart_recovers_running_jobs_without_double_commit(workspace: Any) -> None:
    ctx = build_context(make_settings(workspace))
    from pbs_core.api.app import create_app

    app = create_app(make_settings(workspace), ctx=ctx)
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-PBS-Token": ctx.token}) as client:
        prov = mock_provider(client)
        pid, cid = book(client)
        j = ask(client, pid, cid, prov["id"]).json()
        crashed = JobRunner(ctx)
        assert crashed.claim() == j["id"]  # it was running when the process died
    ctx.close()

    ctx2 = build_context(make_settings(workspace))
    try:
        r2 = JobRunner(ctx2)
        assert r2.recover() == 1
        with ctx2.db.tx() as s:
            row = s.get(Job, j["id"])
            assert row is not None and row.status == "queued"
        r2.run_until_idle()
        # Running the finished job again is a no-op: one proposal, one usage record.
        from pbs_core.jobs.execute import run_job

        run_job(ctx2, j["id"], threading.Event(), threading.Semaphore(1))
        with ctx2.db.tx() as s:
            assert s.get(Job, j["id"]).status == "succeeded"  # type: ignore[union-attr]
            assert len(s.scalars(select(Proposal)).all()) == 1
            assert len(s.scalars(select(UsageRecord)).all()) == 1
            assert s.scalar(text("SELECT head_revision_no FROM chapter WHERE id = :c"), {"c": cid}) == 1
    finally:
        ctx2.close()


def test_recover_marks_exhausted_jobs_interrupted(client: TestClient, ctx: AppContext) -> None:
    prov = mock_provider(client)
    pid, cid = book(client)
    j = ask(client, pid, cid, prov["id"]).json()
    with ctx.db.tx() as s:
        row = s.get(Job, j["id"])
        assert row is not None
        row.status, row.attempt, row.max_attempts = "running", 3, 3
    JobRunner(ctx).recover()
    out = job(client, j["id"])
    assert out["status"] == "interrupted" and "Retry" in out["error_message"]


def test_no_model_chosen_is_an_explicit_error(client: TestClient) -> None:
    mock_provider(client)
    pid, cid = book(client)
    body = {"chapter_id": cid, "task": "draft", "base_revision_no": 1, "client_request_id": uuid.uuid4().hex}
    r = client.post(f"/api/projects/{pid}/ai/jobs", json=body)
    assert r.status_code == 409 and r.json()["code"] == "model_not_chosen"


def test_task_route_is_used_and_estimate_is_labelled(client: TestClient, runner: JobRunner) -> None:
    prov = mock_provider(client)
    pid, cid = book(client)
    put = client.put(
        "/api/ai/routes/draft", json={"provider_id": prov["id"], "model_name": "mock-writer", "max_output_tokens": 300}
    )
    assert put.status_code == 200
    body = {"chapter_id": cid, "task": "draft", "base_revision_no": 1, "client_request_id": uuid.uuid4().hex}
    est = client.post(f"/api/projects/{pid}/ai/estimate", json=body).json()
    assert est["is_estimate"] is True and est["max_output_tokens"] == 300 and est["cost_upper_bound"] == "0"
    assert "Estimate" in est["basis"] and est["blocked_reason"] is None
    j = client.post(f"/api/projects/{pid}/ai/jobs", json=body).json()
    assert j["model_name"] == "mock-writer"


def test_usage_records_are_immutable(client: TestClient, ctx: AppContext, runner: JobRunner) -> None:
    prov = mock_provider(client)
    pid, cid = book(client)
    ask(client, pid, cid, prov["id"])
    runner.run_until_idle()
    with pytest.raises(Exception, match="immutable"), ctx.db.tx() as s:
        s.execute(text("UPDATE usage_record SET input_tokens = 0"))


def test_status_center_endpoints(client: TestClient, runner: JobRunner) -> None:
    before = external_requests()
    prov = mock_provider(client)
    pid, cid = book(client)
    ask(client, pid, cid, prov["id"])
    runner.run_until_idle()
    jobs = client.get("/api/ai/jobs").json()
    assert jobs[0]["project_title"] == "The Quiet Engine" and jobs[0]["chapter_title"] == "Chapter One"
    st = client.get("/api/ai/status").json()
    assert st["privacy_mode"] == "local_only" and st["pending_proposals"] == 1
    assert st["external_requests"] == before  # nothing new in this local-only test
    assert st["secret_store"]["backend"] == "memory"


def test_approved_chapter_blocks_requests_and_accepts(client: TestClient, runner: JobRunner) -> None:
    prov = mock_provider(client)
    pid, cid = book(client)
    ask(client, pid, cid, prov["id"])
    runner.run_until_idle()
    prop = client.get(f"/api/projects/{pid}/proposals").json()[0]
    assert client.patch(f"/api/projects/{pid}/chapters/{cid}", json={"status": "approved"}).status_code == 200
    r = ask(client, pid, cid, prov["id"])
    assert r.status_code == 409 and r.json()["reason"] == "chapter_approved"
    a = client.post(f"/api/projects/{pid}/proposals/{prop['id']}/accept", json={"expected_head_no": 1})
    assert a.status_code == 409
    assert client.get(f"/api/projects/{pid}/chapters/{cid}/content").json()["revision_no"] == 1
