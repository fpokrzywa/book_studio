"""Phase 06: section-by-section drafting, editor actions, quality reviews, continuity, originality."""

from __future__ import annotations

import io
import uuid
from typing import Any

from fastapi.testclient import TestClient

from pbs_core.context import AppContext
from pbs_core.jobs.runner import JobRunner
from pbs_core.providers.base import GenRequest
from pbs_core.storage.ai_models import Job
from tests.conftest import new_chapter, save
from tests.test_planning import BRIEF, approve_and_apply, mock_provider, new_book, outline_from_ai, rid

MOCK = {"model_name": "mock-writer"}


def run_body(prov: str, **kw: Any) -> dict[str, Any]:
    return {"mode": "entire_book", "provider_id": prov, **MOCK, "client_request_id": rid(), **kw}


def plan(client: TestClient, pid: str, plan_id: str) -> dict[str, Any]:
    r = client.get(f"/api/projects/{pid}/writing/plans/{plan_id}")
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def custom_outline(client: TestClient, pid: str, chapters: list[dict[str, Any]]) -> None:
    r = client.put(f"/api/projects/{pid}/outlines/draft", json={"nodes": chapters})
    assert r.status_code == 200, r.text
    approve_and_apply(client, pid, r.json()["id"])


def chapter_node(
    title: str, sections: list[tuple[str, str]], *, fiction: bool = False, words: int = 600
) -> dict[str, Any]:
    req = (
        {"plot_points": [], "characters": [], "continuity": []}
        if fiction
        else {"citations_min": 0, "source_ids": [], "notes": []}
    )
    return {
        "kind": "chapter",
        "title": title,
        "goal": f"Goal of {title}",
        "target_words": words,
        "requirements": req,
        "children": [{"kind": "section", "title": t, "goal": g} for t, g in sections],
    }


def run_quality(client: TestClient, pid: str, **kw: Any) -> dict[str, Any]:
    r = client.post(f"/api/projects/{pid}/writing/quality/run", json=kw)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def of(findings: list[dict[str, Any]], check: str, present: bool = True) -> list[dict[str, Any]]:
    return [f for f in findings if f["check"] == check and f["present"] is present]


# ---------- acceptance: a short three-chapter book, stop, resume, job history ----------


def test_three_chapter_book_by_section_with_pause_resume_and_history(
    client: TestClient, runner: JobRunner, captured: list[GenRequest]
) -> None:
    pid = new_book(client, desired_chapters=3)["project"]["id"]
    prov = mock_provider(client)
    approve_and_apply(client, pid, outline_from_ai(client, runner, pid, prov)["id"])
    chapters = client.get(f"/api/projects/{pid}/chapters").json()
    assert len(chapters) == 3

    est = client.post(f"/api/projects/{pid}/runs/estimate", json=run_body(prov)).json()
    assert [c["sections"] for c in est["chapters"]] == [2, 2, 2] and est["eligible_count"] == 3
    run = client.post(f"/api/projects/{pid}/runs", json=run_body(prov)).json()
    assert len(run["plan_ids"]) == 3 and len(run["job_ids"]) == 1  # one section at a time
    p1, p2, p3 = run["plan_ids"]
    assert plan(client, pid, p2)["status"] == "waiting"

    # First section done; stop (pause) before the second one starts.
    assert runner.run_once()
    first = plan(client, pid, p1)
    assert [x["state"] for x in first["sections"]] == ["done", "queued"]
    ctx_report = first["sections"][0]["context"]
    parts = {p["key"]: p for p in ctx_report["parts"]}
    assert parts["brief"]["status"] == "included" and parts["outline"]["required"] is True
    assert ctx_report["is_estimate"] is True and ctx_report["used_tokens"] <= ctx_report["budget_tokens"]
    assert first["sections"][0]["provenance"]["model"] == "mock-writer"
    assert first["sections"][0]["provenance"]["template"].startswith("section@")

    paused = client.post(f"/api/projects/{pid}/writing/plans/{p1}/pause").json()
    assert paused["status"] == "paused" and [x["state"] for x in paused["sections"]] == ["done", "pending"]
    assert runner.run_until_idle() == 0  # nothing runs while paused
    assert client.get(f"/api/projects/{pid}/runs").json()[0]["status"] == "running"

    # Resume: the finished section is not sent again; the book completes chapter by chapter.
    resumed = client.post(f"/api/projects/{pid}/writing/plans/{p1}/resume").json()
    assert resumed["status"] == "running"
    runner.run_until_idle()
    plans = [plan(client, pid, x) for x in (p1, p2, p3)]
    assert [p["status"] for p in plans] == ["ready", "ready", "ready"]
    assert plans[0]["sections"][0]["attempts"] == 1 and plans[0]["sections"][1]["attempts"] == 2
    assert client.get(f"/api/projects/{pid}/runs").json()[0]["status"] == "done"

    # Later chapters were given summaries of earlier ones, not their full text.
    prompts = [r.messages[-1].content for r in captured]
    assert any('label="summaries of earlier chapters"' in m and "[Test model output] Covers" in m for m in prompts)

    # One suggestion per chapter, assembled from the sections; nothing applied to the manuscript.
    props = client.get(f"/api/projects/{pid}/proposals").json()
    assert {p["chapter_id"] for p in props} == {c["id"] for c in chapters}
    one = next(p for p in props if p["chapter_id"] == chapters[0]["id"])
    assert one["payload_md"].count("\n## ") + one["payload_md"].startswith("## ") == 2
    assert one["provenance"]["pipeline"]["plan_id"] == p1 and len(one["provenance"]["pipeline"]["sections"]) == 2
    for c in chapters:
        assert client.get(f"/api/projects/{pid}/chapters/{c['id']}/content").json()["revision_no"] == 0

    # Draft job history: every attempt with provider, model, template, usage and its log.
    hist = client.get(f"/api/projects/{pid}/writing/plans/{p1}/history").json()
    assert [(h["section"][:2], h["attempt_no"], h["status"]) for h in hist] == [
        ("1.", 1, "succeeded"),
        ("2.", 1, "cancelled"),
        ("2.", 2, "succeeded"),
    ]
    assert all(h["model_name"] == "mock-writer" and h["provider_kind"] == "mock" for h in hist)
    assert hist[0]["template"].startswith("section@") and hist[0]["output_tokens"]
    logs = " ".join(x["message"] for x in hist[0]["logs"])
    assert "Context for section 1" in logs and "stored on the draft plan (not in the chapter)" in logs
    assert "paused" in hist[1]["error_message"]


def test_failed_section_is_retried_alone(client: TestClient, runner: JobRunner) -> None:
    pid = new_book(client)["project"]["id"]
    prov = mock_provider(client)
    custom_outline(client, pid, [chapter_node("One", [("Alpha", "first part"), ("Beta", "second [[mock:fail_once]]")])])
    run = client.post(f"/api/projects/{pid}/runs", json=run_body(prov)).json()
    runner.run_until_idle()
    p = plan(client, pid, run["plan_ids"][0])
    assert [x["state"] for x in p["sections"]] == ["done", "failed"]
    assert "failed on purpose" in p["sections"][1]["error"] and "Retry it" in p["next_step"]
    alpha = p["sections"][0]["output_md"]
    sid_a, sid_b = p["sections"][0]["id"], p["sections"][1]["id"]
    no = client.post(f"/api/projects/{pid}/writing/plans/{p['id']}/sections/{sid_a}/retry")
    assert no.status_code == 409 and "never drafted again" in no.json()["title"]
    assert client.post(f"/api/projects/{pid}/writing/plans/{p['id']}/sections/{sid_b}/retry").status_code == 200
    runner.run_until_idle()
    p = plan(client, pid, p["id"])
    assert p["status"] == "ready" and p["sections"][0]["output_md"] == alpha
    assert p["sections"][0]["attempts"] == 1 and p["sections"][1]["attempts"] == 2


def test_review_gate_lets_the_author_edit_each_section(client: TestClient, runner: JobRunner) -> None:
    pid = new_book(client)["project"]["id"]
    prov = mock_provider(client)
    custom_outline(client, pid, [chapter_node("One", [("Alpha", "a"), ("Beta", "b")])])
    run = client.post(f"/api/projects/{pid}/runs", json=run_body(prov, review_gate="each_section")).json()
    runner.run_until_idle()
    p = plan(client, pid, run["plan_ids"][0])
    assert p["status"] == "awaiting_review" and [x["state"] for x in p["sections"]] == ["done", "pending"]
    sid = p["sections"][0]["id"]
    ok = client.post(
        f"/api/projects/{pid}/writing/plans/{p['id']}/sections/{sid}/approve", json={"edited_md": "My corrected text."}
    ).json()
    assert ok["sections"][0]["edited"] is True and ok["sections"][0]["reviewed"] is True
    runner.run_until_idle()
    p = plan(client, pid, p["id"])
    assert p["status"] == "awaiting_review"
    client.post(f"/api/projects/{pid}/writing/plans/{p['id']}/sections/{p['sections'][1]['id']}/approve", json={})
    p = plan(client, pid, p["id"])
    prop = client.get(f"/api/projects/{pid}/proposals").json()[0]
    assert p["status"] == "ready" and "My corrected text." in prop["payload_md"]


def test_token_budget_trims_context_and_reports_it(
    client: TestClient, runner: JobRunner, captured: list[GenRequest]
) -> None:
    pid = new_book(client)["project"]["id"]
    prov = mock_provider(client)
    custom_outline(client, pid, [chapter_node("One", [("Alpha", "a")])])
    cid = client.get(f"/api/projects/{pid}/chapters").json()[0]["id"]
    long_text = "\n\n".join(f"Paragraph {i} about carburettors and float bowls in detail." for i in range(600))
    assert save(client, pid, cid, long_text + "\n", 0).status_code == 200
    run = client.post(
        f"/api/projects/{pid}/runs", json=run_body(prov, mode="one_chapter", chapter_ids=[cid], token_budget=1500)
    ).json()
    runner.run_until_idle()
    p = plan(client, pid, run["plan_ids"][0])
    report = p["sections"][0]["context"]
    parts = {x["key"]: x for x in report["parts"]}
    assert parts["so_far"]["status"] == "trimmed" and report["used_tokens"] <= report["budget_tokens"]
    sent = captured[-1].messages[-1].content
    assert "trimmed to fit the token budget" in sent and "Paragraph 599" in sent and "Paragraph 0 " not in sent
    assert len(sent) < 1500 * 4 + 2000  # within the budget (estimate) plus the fixed instructions


# ---------- acceptance: generated content never supersedes locked or approved material ----------


def test_locked_and_approved_chapters_are_never_superseded(client: TestClient, runner: JobRunner) -> None:
    pid = new_book(client, desired_chapters=3)["project"]["id"]
    prov = mock_provider(client)
    approve_and_apply(client, pid, outline_from_ai(client, runner, pid, prov)["id"])
    c1, c2, c3 = client.get(f"/api/projects/{pid}/chapters").json()
    save(client, pid, c1["id"], "My approved opening.\n", 0)
    client.patch(f"/api/projects/{pid}/chapters/{c1['id']}", json={"status": "approved"})
    assert client.patch(f"/api/projects/{pid}/chapters/{c2['id']}", json={"locked": True}).json()["locked"] is True

    est = client.post(f"/api/projects/{pid}/runs/estimate", json=run_body(prov)).json()
    reasons = {x["chapter_id"]: x["reason"] for x in est["chapters"] if not x["eligible"]}
    assert set(reasons) == {c1["id"], c2["id"]} and all("Locked or approved" in r for r in reasons.values())
    assert (
        client.post(
            f"/api/projects/{pid}/runs", json=run_body(prov, mode="one_chapter", chapter_ids=[c1["id"]])
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/projects/{pid}/ai/jobs",
            json={
                "chapter_id": c2["id"],
                "task": "draft",
                "base_revision_no": 0,
                "provider_id": prov,
                **MOCK,
                "client_request_id": rid(),
            },
        ).status_code
        == 409
    )

    client.post(f"/api/projects/{pid}/runs", json=run_body(prov))
    runner.run_until_idle()
    props = client.get(f"/api/projects/{pid}/proposals").json()
    assert [p["chapter_id"] for p in props] == [c3["id"]]

    # Locked after drafting: the suggestion cannot be applied until the author unlocks the chapter.
    client.patch(f"/api/projects/{pid}/chapters/{c3['id']}", json={"locked": True})
    prop = client.get(f"/api/projects/{pid}/proposals/{props[0]['id']}").json()
    assert prop["applicable"] is False and "locked" in prop["not_applicable_reason"]
    refused = client.post(f"/api/projects/{pid}/proposals/{prop['id']}/accept", json={"expected_head_no": 0})
    assert refused.status_code == 409
    assert client.get(f"/api/projects/{pid}/chapters/{c3['id']}/content").json()["revision_no"] == 0
    assert (
        client.get(f"/api/projects/{pid}/chapters/{c1['id']}/content").json()["source_md"] == "My approved opening.\n"
    )
    assert client.get(f"/api/projects/{pid}/chapters/{c2['id']}/content").json()["revision_no"] == 0

    client.patch(f"/api/projects/{pid}/chapters/{c3['id']}", json={"locked": False})
    ok = client.post(f"/api/projects/{pid}/proposals/{prop['id']}/accept", json={"expected_head_no": 0})
    assert ok.status_code == 200 and ok.json()["save"]["content"]["revision_no"] == 1


# ---------- editor actions ----------

CODE_TEXT = (
    "Intro paragraph here.\n\n"
    "Use `oil --check` and remember $E = mc^2$ always.\n\n"
    '```python\nprint("hi")\n```\n\n'
    "End.\n"
)


def _action(client: TestClient, pid: str, cid: str, prov: str, action: str, **kw: Any) -> Any:
    start = CODE_TEXT.index("Use `oil")
    end = CODE_TEXT.index("```\n\nEnd") + 3
    body = {
        "chapter_id": cid,
        "task": "revise",
        "base_revision_no": 1,
        "provider_id": prov,
        **MOCK,
        "selection_start": start,
        "selection_end": end,
        "action": action,
        "client_request_id": uuid.uuid4().hex,
        **kw,
    }
    return client.post(f"/api/projects/{pid}/ai/jobs", json=body)


def test_editor_actions_keep_code_and_math_and_show_a_diff(client: TestClient, runner: JobRunner) -> None:
    pid = new_book(client)["project"]["id"]
    prov = mock_provider(client)
    cid = new_chapter(client, pid)["id"]
    save(client, pid, cid, CODE_TEXT, 0)

    assert _action(client, pid, cid, prov, "clarity").status_code == 202
    runner.run_until_idle()
    prop = client.get(f"/api/projects/{pid}/proposals").json()[0]
    assert prop["mode"] == "replace_selection"
    for kept in ("`oil --check`", "$E = mc^2$", '```python\nprint("hi")\n```'):
        assert kept in prop["payload_md"]
    assert prop["provenance"]["knowledge"]["protected"]["protected_spans"] == 3
    assert prop["provenance"]["knowledge"]["editor_action"] == "clarity"
    ops = {d["op"] for d in prop["diff"]}
    assert {"equal", "insert"} <= ops and "".join(d["text"] for d in prop["diff"] if d["op"] != "insert") == prop[
        "original_text"
    ]

    # A reply that drops protected code or math is never offered.
    bad_r = _action(client, pid, cid, prov, "shorten", instruction="[[mock:drop_code]]")
    assert bad_r.status_code == 202, bad_r.text
    bad = bad_r.json()
    for _ in range(3):  # invalid output is retried; skip the backoff wait between attempts
        runner.run_once()
        with runner.ctx.db.tx() as s:
            row = s.get(Job, bad["id"])
            assert row is not None
            row.run_after = runner.ctx.clock.iso()
    runner.run_until_idle()
    job = client.get(f"/api/ai/jobs/{bad['id']}").json()
    assert (
        job["status"] == "failed" and job["error_code"] == "invalid_output" and "protected code" in job["error_message"]
    )
    assert len(client.get(f"/api/projects/{pid}/proposals").json()) == 1

    assert _action(client, pid, cid, prov, "tone").status_code == 422  # say which tone
    quiz = _action(client, pid, cid, prov, "quiz").json()
    note = _action(client, pid, cid, prov, "explain").json()
    runner.run_until_idle()
    props = {p["job_id"]: p for p in client.get(f"/api/projects/{pid}/proposals").json()}
    assert (
        props[quiz["id"]]["mode"] == "insert_at"
        and props[quiz["id"]]["selection_start"] == CODE_TEXT.index("```\n\nEnd") + 3
    )
    assert props[note["id"]]["mode"] == "note"


# ---------- acceptance: unsupported facts, repeated paragraphs, other checks ----------

FACTS_TEXT = (
    "# Oil\n\n"
    "Most small engines fail because owners skip oil changes. In 2019, 64% of mower repairs were caused by old oil. "
    "Studies show that fresh oil doubles engine life.\n\n"
    "Change the oil every season [@torque-handbook, p. 3]. The handbook gives 1,200 hours as a typical life "
    "[@torque-handbook].\n\n"
    "Keep the mower clean and dry.\n"
)


def test_unsupported_facts_are_marked_and_reviewed(client: TestClient) -> None:
    pid = new_book(client)["project"]["id"]
    cid = new_chapter(client, pid, "Oil")["id"]
    save(client, pid, cid, FACTS_TEXT, 0)
    out = run_quality(client, pid, chapter_id=cid, checks=["unsupported_claim"])
    claims = of(out["findings"], "unsupported_claim")
    assert sorted(c["excerpt"] for c in claims) == [
        "In 2019, 64% of mower repairs were caused by old oil.",
        "Studies show that fresh oil doubles engine life.",
    ]
    assert "do not decide whether a statement is true" in out["disclaimer"]
    a, b = sorted(claims, key=lambda c: c["excerpt"])
    r = client.patch(
        f"/api/projects/{pid}/writing/quality/{a['id']}", json={"state": "needs_source", "note": "Find the survey."}
    )
    assert r.json()["state"] == "needs_source"
    client.patch(f"/api/projects/{pid}/writing/quality/{b['id']}", json={"state": "dismissed", "note": "Opinion."})

    again = run_quality(client, pid, chapter_id=cid, checks=["unsupported_claim"])
    assert again["new"] == 0 and again["seen"] == 2
    states = {f["excerpt"]: (f["state"], f["note"]) for f in of(again["findings"], "unsupported_claim")}
    assert states[a["excerpt"]] == ("needs_source", "Find the survey.") and states[b["excerpt"]][0] == "dismissed"

    # Citing the paragraph resolves both: the findings stay (with their decisions) but are no longer present.
    fixed = FACTS_TEXT.replace("engine life.\n", "engine life [@oil-survey].\n")
    save(client, pid, cid, fixed, 1)
    last = run_quality(client, pid, chapter_id=cid, checks=["unsupported_claim"])
    assert (
        of(last["findings"], "unsupported_claim") == [] and len(of(last["findings"], "unsupported_claim", False)) == 2
    )


REPEATED = "Drain the old oil while the engine is warm so that it flows out quickly and carries the dirt with it."


def test_repeated_paragraph_check_finds_a_real_duplicate(client: TestClient) -> None:
    pid = new_book(client)["project"]["id"]
    a = new_chapter(client, pid, "Draining")["id"]
    b = new_chapter(client, pid, "Refilling")["id"]
    save(client, pid, a, f"# Draining\n\n{REPEATED}\n\nThen let it settle for a while.\n", 0)
    phrase = "keep the blade sharp and balanced"
    save(
        client,
        pid,
        b,
        f"# Refilling\n\nFirst things first.\n\n{REPEATED}\n\nAlways {phrase}. You must {phrase}. Remember to {phrase}.\n",
        0,
    )
    out = run_quality(client, pid, checks=["duplicate_paragraph", "repeated_phrase"])
    dups = of(out["findings"], "duplicate_paragraph")
    assert len(dups) == 1 and dups[0]["severity"] == "warning"
    locs = {(x["chapter_id"], x["paragraph"]) for x in dups[0]["details"]["locations"]}
    assert locs == {(a, 1), (b, 2)} and dups[0]["excerpt"] == REPEATED
    phrases = of(out["findings"], "repeated_phrase")
    assert any("keep the blade sharp and" in f["message"] and f["details"]["count"] == 3 for f in phrases)


def test_links_alt_terms_acronyms_exclusions_and_gated_code_checks(client: TestClient) -> None:
    pid = new_book(client)["project"]["id"]
    cid = new_chapter(client, pid, "Setup")["id"]
    text = (
        "## Setup {#setup}\n\n"
        "See [the setup](#setup), [a missing part](#nowhere) and [a bad address](http://).\n\n"
        "![](assets/x.png)\n\n"
        "Send an e-mail to the dealer. Every email gets an answer. Engage the PTO lever. "
        "The Engine Control Unit (ECU) checks the ECU codes.\n\n"
        "Diesel engines are different.\n\n"
        "```python\ndef broken(:\n    pass\n```\n"
    )
    save(client, pid, cid, text, 0)
    out = run_quality(client, pid)
    msgs = {f["check"]: [x["message"] for x in of(out["findings"], f["check"])] for f in out["findings"]}
    assert any("#nowhere" in m for m in msgs["broken_link"]) and any(
        "not a complete web address" in m for m in msgs["broken_link"]
    )
    assert not any("#setup" in m for m in msgs["broken_link"])
    assert msgs["missing_alt"]
    assert any("“e-mail”" in m and "“email”" in m for m in msgs["inconsistent_term"])
    assert any("“PTO”" in m for m in msgs["undefined_acronym"]) and not any(
        "ECU" in m for m in msgs["undefined_acronym"]
    )
    assert any("Diesel engines" in m for m in msgs["outline_mismatch"])
    assert "code_syntax" not in msgs and "code_syntax" in out["checks_skipped"]

    settings = client.put(f"/api/projects/{pid}/writing/settings", json={"code_check_authorized": True}).json()
    assert settings["code_check_authorized"] is True and "never run" in settings["code_check_note"]
    code = of(run_quality(client, pid, checks=["code_syntax"])["findings"], "code_syntax")
    assert len(code) == 1 and "the code was not run" in code[0]["message"]


# ---------- fiction: continuity memory ----------


def fiction_book(client: TestClient) -> str:
    body = {
        "project": {"title": "Night Shift", "project_type": "fiction", "target_word_count": 3000},
        "brief": {**BRIEF, "kind": "fiction", "exclusions": []},
    }
    r = client.post("/api/books", json=body)
    assert r.status_code == 201, r.text
    return r.json()["project"]["id"]  # type: ignore[no-any-return]


def test_fiction_continuity_memory_and_checks(
    client: TestClient, runner: JobRunner, captured: list[GenRequest]
) -> None:
    pid = fiction_book(client)
    prov = mock_provider(client)
    custom_outline(
        client,
        pid,
        [
            chapter_node("Arrival", [("Gate", "Mara arrives")], fiction=True),
            chapter_node("Storm", [("Flood", "[[mock:conflict]] the storm breaks")], fiction=True),
        ],
    )
    client.post(f"/api/projects/{pid}/runs", json=run_body(prov))
    runner.run_until_idle()
    facts = client.get(f"/api/projects/{pid}/writing/facts").json()
    eyes = sorted((f["value"], f["status"], f["origin"]) for f in facts if f["attribute"] == "eye colour")
    assert eyes == [("brown", "proposed", "ai_extracted"), ("green", "proposed", "ai_extracted")]
    storm_prompt = next(r.messages[-1].content for r in captured if "Chapter: Storm" in r.messages[-1].content)
    assert 'label="continuity notes"' in storm_prompt and "Mara eye colour: green" in storm_prompt

    out = run_quality(client, pid, checks=["continuity"])
    cont = of(out["findings"], "continuity")
    assert any("Mara" in f["message"] and "different values" in f["message"] for f in cont)
    assert any("chronology" in f["message"].lower() for f in cont)
    assert "unsupported_claim" not in out["checks_run"]

    # The author rejects the wrong fact: the conflict is gone on the next run; timeline entries stay.
    brown = next(f for f in facts if f["value"] == "brown")
    client.patch(f"/api/projects/{pid}/writing/facts/{brown['id']}", json={"status": "rejected"})
    client.post(
        f"/api/projects/{pid}/writing/facts",
        json={"kind": "thread", "name": "The missing key", "value": "Who took it?"},
    )
    again = run_quality(client, pid, checks=["continuity"])
    msgs = [f["message"] for f in of(again["findings"], "continuity")]
    assert not any("different values" in m for m in msgs) and any("Open story thread" in m for m in msgs)
    summaries = client.get(f"/api/projects/{pid}/writing/summaries").json()
    assert all(s["text"] for s in summaries) and "waits for your review" in summaries[0]["basis"]


# ---------- AI review and originality ----------


def test_ai_review_keeps_only_findings_quoted_from_the_chapter(client: TestClient, runner: JobRunner) -> None:
    pid = new_book(client)["project"]["id"]
    prov = mock_provider(client)
    cid = new_chapter(client, pid, "Oil")["id"]
    save(client, pid, cid, FACTS_TEXT, 0)
    job = client.post(
        f"/api/projects/{pid}/writing/quality/ai-review",
        json={"chapter_id": cid, "provider_id": prov, **MOCK, "client_request_id": rid()},
    )
    assert job.status_code == 202, job.text
    runner.run_until_idle()
    found = [f for f in client.get(f"/api/projects/{pid}/writing/quality").json() if f["origin"] == "ai_review"]
    assert len(found) == 1 and found[0]["excerpt"].startswith("Most small engines fail")
    assert "not a check of factual correctness" in found[0]["details"]["disclaimer"]
    logs = " ".join(x["message"] for x in client.get(f"/api/ai/jobs/{job.json()['id']}/logs").json())
    assert "1 dropped because their quote is not in the chapter" in logs


def test_originality_report_states_its_scope(client: TestClient) -> None:
    shared = "The float bowl keeps a small reserve of fuel so that the engine never starves while it is running hard."
    pid = new_book(client)["project"]["id"]
    cid = new_chapter(client, pid, "Fuel")["id"]
    save(
        client, pid, cid, f"# Fuel\n\n{shared}\n\nThis paragraph is my own and appears nowhere else at all today.\n", 0
    )
    other = new_book(client)["project"]["id"]
    save(client, other, new_chapter(client, other, "Copy")["id"], f"Intro.\n\n{shared}\n", 0)
    src_text = b"# Handbook\n\nTighten the spark plug a quarter turn past finger tight and never use a power tool on the threads."
    client.post(f"/api/projects/{pid}/knowledge/sources", files={"file": ("handbook.md", src_text)})
    save(
        client,
        pid,
        cid,
        f"# Fuel\n\n{shared}\n\nTighten the spark plug a quarter turn past finger tight and never use a power tool.\n",
        1,
    )
    rep = client.get(f"/api/projects/{pid}/writing/originality").json()
    kinds = {o["kind"] for o in rep["overlaps"]}
    assert kinds == {"workspace_book", "knowledge_source"}
    assert "does not mean the text is original" in rep["statement"]
    assert "No external similarity provider is configured" in rep["external_provider"]
    assert any("web" in x for x in rep["not_covered"])


def test_backup_keeps_continuity_summaries_and_finding_decisions(client: TestClient) -> None:
    pid = new_book(client)["project"]["id"]
    cid = new_chapter(client, pid, "Oil")["id"]
    save(client, pid, cid, FACTS_TEXT, 0)
    client.post(
        f"/api/projects/{pid}/writing/facts", json={"kind": "term", "name": "Float bowl", "value": "Fuel reserve."}
    )
    client.put(f"/api/projects/{pid}/writing/summaries/{cid}", json={"text": "Why oil matters."})
    claim = of(run_quality(client, pid, checks=["unsupported_claim"])["findings"], "unsupported_claim")[0]
    client.patch(f"/api/projects/{pid}/writing/quality/{claim['id']}", json={"state": "dismissed"})
    blob = client.get(f"/api/backups/{client.post(f'/api/projects/{pid}/backups').json()['id']}/file").content
    rp = client.post("/api/backups/restore", files={"file": ("b.zip", io.BytesIO(blob), "application/zip")}).json()[
        "project"
    ]["id"]
    assert client.get(f"/api/projects/{rp}/writing/facts").json()[0]["name"] == "Float bowl"
    assert client.get(f"/api/projects/{rp}/writing/summaries").json()[0]["text"] == "Why oil matters."
    again = run_quality(client, rp, checks=["unsupported_claim"])
    assert again["new"] == 0
    states = {f["excerpt"]: f["state"] for f in of(again["findings"], "unsupported_claim")}
    assert states[claim["excerpt"]] == "dismissed"


def test_writing_routes_are_project_scoped(client: TestClient, ctx: AppContext) -> None:
    a = new_book(client)["project"]["id"]
    b = new_book(client)["project"]["id"]
    fact = client.post(f"/api/projects/{a}/writing/facts", json={"kind": "term", "name": "X", "value": "Y"}).json()
    assert client.patch(f"/api/projects/{b}/writing/facts/{fact['id']}", json={"status": "rejected"}).status_code == 404
    assert client.get(f"/api/projects/{b}/writing/plans/01M829KD3M11NYD021ACCTQTEM").status_code == 404
