"""Phase 05: New Book wizard, brief, research (no invented market figures), outlines, skeleton, runs."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from pbs_core.context import AppContext
from pbs_core.jobs.runner import JobRunner
from pbs_core.providers.base import GenRequest
from tests.conftest import save

BRIEF = {
    "kind": "nonfiction",
    "genre": "How-to",
    "purpose": "Help owners keep small engines running.",
    "promise": "Keep a small engine running for years with one hour a month",
    "tone": "Plain and encouraging",
    "desired_chapters": 4,
    "target_reader": "First-time owners",
    "exclusions": ["Diesel engines"],
    "assumptions": [{"kind": "factual", "text": "Readers own basic hand tools."}],
}


def rid() -> str:
    return uuid.uuid4().hex


def new_book(client: TestClient, **brief: Any) -> dict[str, Any]:
    body = {
        "project": {
            "title": "The Quiet Engine",
            "project_type": "nonfiction",
            "target_word_count": 20000,
            "audience": "Hobbyists",
        },
        "brief": {**BRIEF, **brief},
    }
    r = client.post("/api/books", json=body)
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def mock_provider(client: TestClient) -> str:
    return client.post("/api/ai/providers", json={"kind": "mock"}).json()["id"]  # type: ignore[no-any-return]


def outline_from_ai(client: TestClient, runner: JobRunner, pid: str, prov: str, **kw: Any) -> dict[str, Any]:
    r = client.post(
        f"/api/projects/{pid}/outlines/generate",
        json={"provider_id": prov, "model_name": "mock-writer", "client_request_id": rid(), **kw},
    )
    assert r.status_code == 202, r.text
    runner.run_until_idle()
    job = client.get(f"/api/ai/jobs/{r.json()['id']}").json()
    assert job["status"] == "succeeded", job
    return next(o for o in client.get(f"/api/projects/{pid}/outlines").json() if o["status"] == "proposed")


def approve_and_apply(client: TestClient, pid: str, oid: str) -> dict[str, Any]:
    assert client.post(f"/api/projects/{pid}/outlines/{oid}/approve").status_code == 200
    r = client.post(f"/api/projects/{pid}/outlines/{oid}/apply")
    assert r.status_code == 200, r.text
    return r.json()["report"]  # type: ignore[no-any-return]


# ---------- wizard and brief ----------


def test_wizard_creates_book_brief_and_links_sources(client: TestClient) -> None:
    lib = client.post("/api/knowledge/libraries", json={"name": "Shared refs"}).json()
    profile = client.post("/api/voice/profiles", json={"name": "Sam"}).json()
    out = client.post(
        "/api/books",
        json={
            "project": {
                "title": "Field Manual",
                "project_type": "course",
                "language": "en",
                "audience": "Mechanics",
                "target_word_count": 40000,
                "publication_formats": ["ebook", "paperback"],
            },
            "brief": {
                **BRIEF,
                "kind": "manual",
                "author_profile_id": profile["id"],
                "approval_preference": "review_outline_then_batch",
                "budget_cap": "5.00",
                "budget_currency": "USD",
                "max_chapters_per_run": 3,
            },
            "shared_library_ids": [lib["id"]],
        },
    ).json()
    pid = out["project"]["id"]
    assert out["brief"]["kind"] == "manual" and out["brief"]["arc_label"] == "Teaching arc"
    assert out["brief"]["budget_cap"] == "5.00" and out["brief"]["max_chapters_per_run"] == 3
    assert client.get(f"/api/projects/{pid}/knowledge").json()["linked"][0]["id"] == lib["id"]
    assert (
        client.post(
            "/api/books",
            json={
                "project": {"title": "X", "project_type": "fiction"},
                "brief": {"kind": "fiction", "budget_cap": "5"},
            },
        ).status_code
        == 422
    )


def test_brief_approval_and_new_version_on_change(client: TestClient) -> None:
    pid = new_book(client)["project"]["id"]
    b = client.post(f"/api/projects/{pid}/brief/approve").json()
    assert b["status"] == "approved" and b["version"] == 1
    changed = client.put(f"/api/projects/{pid}/brief", json={**BRIEF, "tone": "Wry"}).json()
    assert changed["status"] == "draft" and changed["version"] == 2


# ---------- outline: from idea to approved skeleton, deterministically ----------


def test_idea_to_approved_outline_with_test_model(
    client: TestClient, runner: JobRunner, captured: list[GenRequest]
) -> None:
    pid = new_book(client)["project"]["id"]
    prov = mock_provider(client)
    proposal = outline_from_ai(client, runner, pid, prov)
    sent = captured[-1]
    assert "Desired number of chapters: 4" in sent.messages[-1].content
    assert "Never state, estimate or imply any such figure" in sent.messages[-1].content
    nodes = proposal["nodes"]
    assert proposal["origin"] == "ai_generated" and len(nodes) == 4
    assert all(n["id"].startswith("n_") and len(n["id"]) == 28 for n in nodes)
    assert all(
        n["kind"] == "chapter" and len(n["children"]) == 2 and n["children"][0]["kind"] == "section" for n in nodes
    )
    assert nodes[0]["target_words"] == 5000 and proposal["totals"]["target_words"] == 20000
    assert proposal["totals"]["estimated_writing_hours"] == 40.0  # 20000 words at 500 words/hour
    # Nothing is created until the author approves and applies.
    assert client.get(f"/api/projects/{pid}/chapters").json() == []
    assert client.post(f"/api/projects/{pid}/outlines/{proposal['id']}/apply").status_code == 409
    report = approve_and_apply(client, pid, proposal["id"])
    assert len(report["created"]) == 4
    chapters = client.get(f"/api/projects/{pid}/chapters").json()
    assert [c["title"] for c in chapters] == [n["title"] for n in nodes]  # sections stay inside chapters
    assert all(c["status"] == "planned" for c in chapters)
    with client.app.state.ctx.db.tx() as s:  # type: ignore[attr-defined]
        linked = {r[0] for r in s.execute(text("SELECT outline_node_id FROM chapter")).all()}
    assert linked == {n["id"] for n in nodes}  # stable IDs map outline to manuscript


def test_changed_outline_keeps_prose_history_and_locks(client: TestClient, runner: JobRunner) -> None:
    pid = new_book(client)["project"]["id"]
    prov = mock_provider(client)
    v1 = outline_from_ai(client, runner, pid, prov)
    approve_and_apply(client, pid, v1["id"])
    ch = client.get(f"/api/projects/{pid}/chapters").json()
    c1, c2, c3, c4 = ch
    save(client, pid, c1["id"], "First draft of chapter one.\n", 0)
    save(client, pid, c1["id"], "Second draft of chapter one.\n", 1)
    save(client, pid, c3["id"], "Chapter three has prose.\n", 0)
    client.patch(f"/api/projects/{pid}/chapters/{c4['id']}", json={"status": "approved"})

    nodes = v1["nodes"]
    edited = [
        {**nodes[0], "title": "Getting Started"},  # renamed (has prose)
        {**nodes[3], "title": "Renamed while approved"},  # approved chapter: must not change
        {"kind": "chapter", "title": "A brand new chapter", "goal": "New", "target_words": 3000, "children": []},
    ]  # nodes[1] (empty) and nodes[2] (has prose) removed
    draft = client.put(f"/api/projects/{pid}/outlines/draft", json={"nodes": edited, "based_on_id": v1["id"]}).json()
    assert draft["status"] == "draft" and draft["nodes"][0]["id"] == nodes[0]["id"]  # IDs kept
    report = approve_and_apply(client, pid, draft["id"])
    assert report["created"] == ["A brand new chapter"]
    assert report["archived_empty"] == [c2["title"]]
    assert report["kept_not_in_outline"] == [c3["title"]]
    assert c4["title"] in report["skipped_locked"]

    after = {c["id"]: c for c in client.get(f"/api/projects/{pid}/chapters").json()}
    assert after[c1["id"]]["title"] == "Getting Started"
    assert after[c4["id"]]["title"] == c4["title"]  # approved chapter untouched
    assert c2["id"] not in after and c3["id"] in after
    assert (
        client.get(f"/api/projects/{pid}/chapters/{c1['id']}/content").json()["source_md"]
        == "Second draft of chapter one.\n"
    )
    assert [r["revision_no"] for r in client.get(f"/api/projects/{pid}/chapters/{c1['id']}/revisions").json()] == [2, 1]
    assert (
        client.get(f"/api/projects/{pid}/chapters/{c3['id']}/content").json()["source_md"]
        == "Chapter three has prose.\n"
    )
    # Versions are kept: v1 is superseded, not deleted.
    statuses = {o["version_no"]: o["status"] for o in client.get(f"/api/projects/{pid}/outlines").json()}
    assert statuses == {1: "superseded", 2: "approved"}


def test_ai_regeneration_never_overwrites_draft_and_keeps_locked(client: TestClient, runner: JobRunner) -> None:
    pid = new_book(client)["project"]["id"]
    prov = mock_provider(client)
    mine = [
        {"kind": "chapter", "title": "My locked opening", "locked": True, "children": []},
        {"kind": "chapter", "title": "Scratch idea", "children": []},
    ]
    draft = client.put(f"/api/projects/{pid}/outlines/draft", json={"nodes": mine}).json()
    proposal = outline_from_ai(client, runner, pid, prov)
    titles = [n["title"] for n in proposal["nodes"]]
    assert titles[0] == "My locked opening" and "Scratch idea" not in titles and len(titles) == 5
    assert proposal["provenance"]["kept_locked"] == ["My locked opening"]
    still = next(o for o in client.get(f"/api/projects/{pid}/outlines").json() if o["id"] == draft["id"])
    assert [n["title"] for n in still["nodes"]] == ["My locked opening", "Scratch idea"]  # untouched


def test_outline_structure_is_validated(client: TestClient) -> None:
    pid = new_book(client)["project"]["id"]
    bad = client.put(f"/api/projects/{pid}/outlines/draft", json={"nodes": [{"kind": "section", "title": "Orphan"}]})
    assert bad.status_code == 422
    deep = [
        {
            "kind": "chapter",
            "title": "C",
            "children": [{"kind": "section", "title": "S", "children": [{"kind": "section", "title": "X"}]}],
        }
    ]
    assert client.put(f"/api/projects/{pid}/outlines/draft", json={"nodes": deep}).status_code == 422
    empty = client.put(f"/api/projects/{pid}/outlines/draft", json={"nodes": [{"kind": "part", "title": "P"}]}).json()
    assert client.post(f"/api/projects/{pid}/outlines/{empty['id']}/approve").status_code == 422


# ---------- research: never fabricate market metrics ----------


def test_ai_brainstorm_cannot_carry_market_metrics(client: TestClient, ctx: AppContext, runner: JobRunner) -> None:
    pid = new_book(client)["project"]["id"]
    prov = mock_provider(client)
    r = client.post(
        f"/api/projects/{pid}/research/ideas",
        json={
            "what": "keywords",
            "instruction": "Small engine phrases [[mock:metrics]]",
            "provider_id": prov,
            "model_name": "mock-writer",
            "client_request_id": rid(),
        },
    )
    assert r.status_code == 202
    runner.run_until_idle()
    findings = client.get(f"/api/projects/{pid}/research/findings").json()
    assert len(findings) == 3  # the "bestseller niche worth $2 million" item was removed entirely
    blob = json.dumps([f["text"] for f in findings]).lower()  # the explanatory note is not a claim
    for forbidden in ("monthly searches", "competition", "bsr", "bestseller", "$2 million", "demand", "12,000"):
        assert forbidden not in blob, forbidden
    for f in findings:
        assert f["kind"] == "keyword" and f["evidence"] == "heuristic" and f["origin"] == "ai_brainstorm"
        assert (
            f["metrics"] == {} and "removed_unsupported_metric" in f["flags"] and "no_search_volume_data" in f["flags"]
        )
    job = client.get("/api/ai/jobs").json()[0]
    logs = " ".join(x["message"] for x in client.get(f"/api/ai/jobs/{job['id']}/logs").json())
    assert "unsupported market statement(s) removed" in logs
    # The database refuses metrics on anything but provider data.
    with pytest.raises(Exception, match="CHECK constraint"), ctx.db.tx() as s:
        s.execute(text("UPDATE research_finding SET metrics_json = '{\"sales_rank\": 5}'"))


def test_author_findings_separate_measured_from_heuristic(client: TestClient) -> None:
    pid = new_book(client)["project"]["id"]
    unsourced = client.post(
        f"/api/projects/{pid}/research/findings", json={"kind": "measured", "text": "The market is worth $40 million."}
    )
    assert unsourced.status_code == 422
    note = client.post(
        f"/api/projects/{pid}/research/findings",
        json={"kind": "heuristic", "text": "I think there is high demand for this."},
    ).json()
    assert note["evidence"] == "heuristic" and "unsourced_metric" in note["flags"]
    measured = client.post(
        f"/api/projects/{pid}/research/findings",
        json={
            "kind": "measured",
            "text": "Survey: 61% of owners skip maintenance.",
            "source_title": "Owners Survey 2025",
            "source_url": "https://example.org/survey",
            "source_date": "2025-03",
        },
    ).json()
    assert measured["evidence"] == "measured" and measured["retrieved_at"] and measured["flags"] == []
    comp = client.post(
        f"/api/projects/{pid}/research/findings",
        json={
            "kind": "competitor",
            "text": "Similar title, more theory.",
            "meta": {"title": "Engines 101", "author": "A. N. Other"},
        },
    ).json()
    assert comp["meta"]["title"] == "Engines 101"


def test_ai_finding_cannot_become_measured(client: TestClient, runner: JobRunner) -> None:
    pid = new_book(client)["project"]["id"]
    prov = mock_provider(client)
    client.post(
        f"/api/projects/{pid}/research/ideas",
        json={"what": "topics", "provider_id": prov, "model_name": "mock-writer", "client_request_id": rid()},
    )
    runner.run_until_idle()
    f = client.get(f"/api/projects/{pid}/research/findings").json()[0]
    assert (
        client.patch(f"/api/projects/{pid}/research/findings/{f['id']}", json={"kind": "measured"}).status_code == 422
    )


# ---------- research providers: explicit fail-safe ----------


def test_research_provider_off_blocked_or_down_fails_explicitly(client: TestClient, ctx: AppContext) -> None:
    pid = new_book(client)["project"]["id"]
    calls: list[str] = []

    def down(req: httpx2.Request) -> httpx2.Response:
        calls.append(str(req.url))
        raise httpx2.ConnectError("no route to host")

    ctx.http_transport = httpx2.MockTransport(down)
    q = {"provider": "openlibrary", "query": "small engine repair"}
    off = client.post(f"/api/projects/{pid}/research/search", json=q)
    assert (
        off.status_code == 409 and off.json()["reason"] == "not_configured" and "not turned on" in off.json()["title"]
    )

    client.put("/api/research/providers", json={"openlibrary": True})
    blocked = client.post(f"/api/projects/{pid}/research/search", json=q)  # local-only mode
    assert blocked.status_code == 409 and blocked.json()["reason"] == "blocked" and calls == []

    client.put("/api/ai/privacy", json={"mode": "cloud_allowed", "confirm": True})
    failed = client.post(f"/api/projects/{pid}/research/search", json=q)
    assert failed.status_code == 409 and failed.json()["reason"] == "failed"
    assert "could not be reached" in failed.json()["title"] and "findings are unchanged" in failed.json()["title"]
    assert len(calls) == 1 and calls[0].startswith("https://openlibrary.org/search.json")

    client.put("/api/research/providers", json={"mock": True})
    down_mock = client.post(
        f"/api/projects/{pid}/research/search", json={"provider": "mock", "query": "x [[research:down]]"}
    )
    assert down_mock.status_code == 409
    assert client.get(f"/api/projects/{pid}/research/findings").json() == []  # nothing was invented
    with ctx.db.tx() as s:
        rows = s.execute(text("SELECT status FROM research_query ORDER BY created_at")).scalars().all()
    assert rows == ["blocked", "failed", "failed"]


def test_open_library_results_keep_bibliographic_data_only(client: TestClient, ctx: AppContext) -> None:
    pid = new_book(client)["project"]["id"]
    seen: dict[str, Any] = {}

    def ok(req: httpx2.Request) -> httpx2.Response:
        seen["url"], seen["ua"] = str(req.url), req.headers.get("user-agent")
        return httpx2.Response(
            200,
            json={
                "docs": [
                    {
                        "key": "/works/OL1W",
                        "title": "Small Engine Care",
                        "author_name": ["R. Mechanic"],
                        "first_publish_year": 2019,
                        "publisher": ["Shop Press"],
                        "edition_count": 3,
                        "subject": ["Engines"],
                        "ratings_average": 4.9,
                        "readinglog_count": 99999,
                        "want_to_read_count": 5000,
                    }
                ]
            },
        )

    ctx.http_transport = httpx2.MockTransport(ok)
    client.put("/api/research/providers", json={"openlibrary": True})
    client.put("/api/ai/privacy", json={"mode": "cloud_allowed", "confirm": True})
    res = client.post(
        f"/api/projects/{pid}/research/search", json={"provider": "openlibrary", "query": "engine care"}
    ).json()
    assert "fields=key%2Ctitle%2Cauthor_name" in seen["url"] and "ratings" not in seen["url"]
    assert seen["ua"].startswith("PersonalBookStudio/") and "@" not in seen["ua"]
    hit = res["hits"][0]
    assert hit["title"] == "Small Engine Care" and hit["url"] == "https://openlibrary.org/works/OL1W"
    f = client.post(f"/api/projects/{pid}/research/save", json={"query_id": res["query_id"], "index": 0}).json()
    blob = json.dumps(f)
    assert f["origin"] == "provider" and f["metrics"] == {} and f["source_date"] == "2019"
    assert "4.9" not in blob and "99999" not in blob and "5000" not in blob


# ---------- generation runs: modes, locks, limits, budget ----------


def test_bulk_generation_requires_an_approved_applied_outline(client: TestClient) -> None:
    pid = new_book(client)["project"]["id"]
    prov = mock_provider(client)
    r = client.post(
        f"/api/projects/{pid}/runs/estimate",
        json={"mode": "entire_book", "provider_id": prov, "model_name": "mock-writer"},
    )
    assert r.status_code == 409 and r.json()["reason"] == "outline_not_approved"


def test_entire_book_honours_prose_locks_and_review(
    client: TestClient, runner: JobRunner, captured: list[GenRequest]
) -> None:
    pid = new_book(client)["project"]["id"]
    prov = mock_provider(client)
    approve_and_apply(client, pid, outline_from_ai(client, runner, pid, prov)["id"])
    c1, c2, c3, c4 = client.get(f"/api/projects/{pid}/chapters").json()
    save(client, pid, c1["id"], "My own opening.\n", 0)
    client.patch(f"/api/projects/{pid}/chapters/{c2['id']}", json={"status": "approved"})
    body = {"mode": "entire_book", "provider_id": prov, "model_name": "mock-writer"}
    est = client.post(f"/api/projects/{pid}/runs/estimate", json=body).json()
    assert est["eligible_count"] == 2 and est["cost_upper_bound"] == "0" and est["is_estimate"] is True
    reasons = {x["title"]: x["reason"] for x in est["chapters"] if not x["eligible"]}
    assert "Already has text" in reasons[c1["title"]] and "Locked or approved" in reasons[c2["title"]]
    assert est["minutes_estimate"] is not None or "unknown" in est["time_note"]
    run = client.post(f"/api/projects/{pid}/runs", json={**body, "client_request_id": rid()}).json()
    # Phase 06: one plan per chapter, drafted section by section; only the first section is queued now.
    assert len(run["plan_ids"]) == 2 and len(run["job_ids"]) == 1 and len(run["skipped"]) == 2
    runner.run_until_idle()
    sent = [r.messages[-1].content for r in captured]
    assert any("Write section 2 of 2 of this chapter" in m for m in sent)
    props = client.get(f"/api/projects/{pid}/proposals").json()
    assert {p["chapter_id"] for p in props} == {c3["id"], c4["id"]}
    assert all(p["provenance"]["outline_node_id"] for p in props)
    assert props[0]["provenance"]["requirements_check"] is not None
    # Nothing was applied: every chapter is still as it was.
    for c in (c3, c4):
        assert client.get(f"/api/projects/{pid}/chapters/{c['id']}/content").json()["revision_no"] == 0
    assert client.get(f"/api/projects/{pid}/chapters/{c1['id']}/content").json()["source_md"] == "My own opening.\n"
    assert client.get(f"/api/projects/{pid}/runs").json()[0]["status"] == "done"
    # One-chapter mode may continue a chapter that has text (as a suggestion appended for review).
    one = client.post(
        f"/api/projects/{pid}/runs",
        json={**body, "mode": "one_chapter", "chapter_ids": [c1["id"]], "client_request_id": rid()},
    )
    assert one.status_code == 202 and len(one.json()["job_ids"]) == 1 and len(one.json()["plan_ids"]) == 1


def test_chapter_limit_blocks_large_runs(client: TestClient, runner: JobRunner) -> None:
    pid = new_book(client, max_chapters_per_run=2)["project"]["id"]
    prov = mock_provider(client)
    approve_and_apply(client, pid, outline_from_ai(client, runner, pid, prov)["id"])
    body = {"mode": "entire_book", "provider_id": prov, "model_name": "mock-writer", "client_request_id": rid()}
    r = client.post(f"/api/projects/{pid}/runs", json=body)
    assert r.status_code == 409 and "limit per run is 2" in r.json()["title"]
    ids = [c["id"] for c in client.get(f"/api/projects/{pid}/chapters").json()][:2]
    assert (
        client.post(
            f"/api/projects/{pid}/runs", json={**body, "chapter_ids": ids, "client_request_id": rid()}
        ).status_code
        == 202
    )


SECTION_JSON = json.dumps({"text": "Drafted text.", "summary": "A summary.", "facts": []})


def _cloud(client: TestClient, ctx: AppContext, pid: str) -> str:
    def chat(req: httpx2.Request) -> httpx2.Response:
        body = json.loads(req.content)
        chunks = [
            {
                "id": "c",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "gpt-x",
                "choices": [{"index": 0, "delta": {"content": SECTION_JSON}, "finish_reason": "stop"}],
            },
            {
                "id": "c",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "gpt-x",
                "choices": [],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
            },
        ]
        if not body.get("stream"):
            raise AssertionError("expected streaming")
        data = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx2.Response(200, content=data.encode(), headers={"content-type": "text/event-stream"})

    ctx.http_transport = httpx2.MockTransport(chat)
    prov = client.post("/api/ai/providers", json={"kind": "openai"}).json()["id"]
    client.put(f"/api/ai/providers/{prov}/key", json={"api_key": "sk-test-1234567890"})
    client.put(f"/api/ai/providers/{prov}/models", json={"name": "gpt-x"})
    client.put("/api/ai/privacy", json={"mode": "cloud_allowed", "confirm": True})
    client.put(f"/api/projects/{pid}/ai/consent/{prov}")
    return prov  # type: ignore[no-any-return]


def test_budget_cap_blocks_and_stops_runs(client: TestClient, ctx: AppContext, runner: JobRunner) -> None:
    pid = new_book(client, budget_cap="0.10", budget_currency="USD")["project"]["id"]
    approve_and_apply(client, pid, outline_from_ai(client, runner, pid, mock_provider(client))["id"])
    cloud = _cloud(client, ctx, pid)
    body = {"mode": "entire_book", "provider_id": cloud, "model_name": "gpt-x", "use_sources": False}
    unknown = client.post(f"/api/projects/{pid}/runs/estimate", json=body).json()
    assert unknown["cost_upper_bound"] is None and "cannot be estimated" in unknown["blocked_reason"]
    client.put(
        f"/api/ai/providers/{cloud}/prices",
        json={
            "model_name": "gpt-x",
            "input_per_mtok": "10",
            "output_per_mtok": "30",
            "currency": "USD",
            "as_of": "2026-11-22",
        },
    )
    over = client.post(f"/api/projects/{pid}/runs/estimate", json=body).json()
    assert over["blocked_reason"] and "above the budget cap of 0.10" in over["blocked_reason"]
    assert client.post(f"/api/projects/{pid}/runs", json={**body, "client_request_id": rid()}).status_code == 409

    # A cap the estimate fits, then the price disappears mid-run: the run stops instead of spending blind.
    client.put(f"/api/projects/{pid}/brief", json={**BRIEF, "budget_cap": "50", "budget_currency": "USD"})
    run = client.post(f"/api/projects/{pid}/runs", json={**body, "client_request_id": rid()}).json()
    assert len(run["plan_ids"]) == 4 and len(run["job_ids"]) == 1 and run["budget_cap"] == "50"
    price_id = client.get(f"/api/ai/providers/{cloud}/prices").json()[0]["id"]
    client.delete(f"/api/ai/providers/{cloud}/prices/{price_id}")
    runner.run_once()
    out = client.get(f"/api/projects/{pid}/runs").json()[0]
    assert (
        out["status"] == "stopped"
        and "could not be determined" in out["stop_reason"]
        and out["unknown_cost_calls"] == 1
    )
    statuses = [client.get(f"/api/ai/jobs/{j}").json()["status"] for j in run["job_ids"]]
    assert statuses == ["succeeded"]
    plans = [client.get(f"/api/projects/{pid}/writing/plans/{x}").json() for x in run["plan_ids"]]
    assert {p["status"] for p in plans} == {"cancelled"}
    assert runner.run_until_idle() == 0


def test_backup_restore_keeps_brief_findings_outlines_and_links(client: TestClient, runner: JobRunner) -> None:
    import io

    pid = new_book(client)["project"]["id"]
    prov = mock_provider(client)
    v1 = outline_from_ai(client, runner, pid, prov)
    approve_and_apply(client, pid, v1["id"])
    client.post(
        f"/api/projects/{pid}/research/findings", json={"kind": "note", "text": "Owners forget fuel stabiliser."}
    )
    blob = client.get(f"/api/backups/{client.post(f'/api/projects/{pid}/backups').json()['id']}/file").content
    rp = client.post("/api/backups/restore", files={"file": ("b.zip", io.BytesIO(blob), "application/zip")}).json()[
        "project"
    ]["id"]
    assert client.get(f"/api/projects/{rp}/brief").json()["promise"] == BRIEF["promise"]
    assert client.get(f"/api/projects/{rp}/research/findings").json()[0]["text"] == "Owners forget fuel stabiliser."
    restored = client.get(f"/api/projects/{rp}/outlines").json()
    assert [o["status"] for o in restored] == ["approved"] and restored[0]["nodes"] == v1["nodes"]
    # The restored book can be drafted straight away: chapters still map to the approved outline.
    est = client.post(
        f"/api/projects/{rp}/runs/estimate",
        json={"mode": "entire_book", "provider_id": prov, "model_name": "mock-writer"},
    ).json()
    assert est["eligible_count"] == 4
