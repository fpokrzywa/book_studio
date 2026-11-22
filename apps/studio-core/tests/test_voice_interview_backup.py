"""Phase 04: author voice, interviews (exact words, never invented) and backup/restore of citations."""

from __future__ import annotations

import io
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from pbs_core.context import AppContext
from pbs_core.jobs.runner import JobRunner
from pbs_core.providers.base import GenRequest
from tests.test_knowledge import HANDBOOK, ask, proposal, setup_book, upload

MY_WRITING = """I started fixing engines because my grandfather wouldn't let me drive until I could. He'd hand me a
spanner and walk off. I learned fast. I learned the hard way, too: a stripped bolt, a cracked casing, a long walk home.

Here's what I know now. Engines aren't mysterious. They're patient. You listen, you look, and you don't rush the
torque. Do that and they'll run for years. Skip it and you'll be back in the shed by Sunday — every time.
"""


def profile(client: TestClient) -> dict[str, Any]:
    return client.post("/api/voice/profiles", json={"name": "Sam Writer"}).json()  # type: ignore[no-any-return]


# ---------- author voice ----------


def test_samples_require_rights_confirmation(client: TestClient) -> None:
    p = profile(client)
    r = client.post(
        f"/api/voice/profiles/{p['id']}/samples", json={"title": "Essay", "text": MY_WRITING, "rights_confirmed": False}
    )
    assert r.status_code == 422
    f = client.post(f"/api/voice/profiles/{p['id']}/samples/file", files={"file": ("essay.md", MY_WRITING.encode())})
    assert f.status_code == 422


def test_analysis_metrics_examples_and_editable_guide(client: TestClient) -> None:
    p = profile(client)
    out = client.post(
        f"/api/voice/profiles/{p['id']}/samples", json={"title": "Essay", "text": MY_WRITING, "rights_confirmed": True}
    ).json()
    m = out["metrics"]
    assert m["word_count"] > 80 and m["contractions_per_100_words"] > 1.5
    assert out["labels"]["formality"] == "conversational" and out["labels"]["point_of_view"] == "first person"
    flat = " ".join(MY_WRITING.split())
    assert out["examples"] and all(e["text"] in flat for e in out["examples"])  # exact excerpts only
    assert "Contractions: use them freely" in out["style_guide_md"]
    edited = client.patch(
        f"/api/voice/profiles/{p['id']}",
        json={
            "style_guide_md": "- Short sentences. No semicolons.",
            "corrections": [{"before": "utilise", "after": "use", "note": "plain words"}],
        },
    ).json()
    assert edited["guide_edited"] is True and edited["corrections"][0]["after"] == "use"
    more = client.post(
        f"/api/voice/profiles/{p['id']}/samples/file",
        files={"file": ("more.md", ("A second piece. " * 40).encode())},
        data={"rights_confirmed": "true", "rights_basis": "own_writing"},
    ).json()
    assert more["style_guide_md"] == "- Short sentences. No semicolons."  # re-analysis never overwrites edits
    dup = client.post(
        f"/api/voice/profiles/{p['id']}/samples", json={"title": "Again", "text": MY_WRITING, "rights_confirmed": True}
    )
    assert dup.status_code == 409


def test_style_rewrite_is_preview_only_until_accepted(
    client: TestClient, runner: JobRunner, captured: list[GenRequest]
) -> None:
    pid, cid, prov = setup_book(client, "The engine was examined carefully by the technician.\n")
    p = profile(client)
    client.post(
        f"/api/voice/profiles/{p['id']}/samples", json={"title": "Essay", "text": MY_WRITING, "rights_confirmed": True}
    )
    ask(
        client,
        pid,
        cid,
        prov,
        task="revise",
        mode="replace_selection",
        selection_start=0,
        selection_end=52,
        voice_profile_id=p["id"],
        instruction="Rewrite in my voice.",
    )
    runner.run_until_idle()
    sent = captured[-1].messages[-1].content
    assert 'label="author style guide (style reference only)"' in sent and "Contractions: use them freely" in sent
    prop = proposal(client, pid)
    assert prop["mode"] == "replace_selection" and prop["original_text"].startswith("The engine was examined")
    assert prop["provenance"]["template"].startswith("revise+voice@")
    # Preview only: the chapter is untouched until Accept.
    assert client.get(f"/api/projects/{pid}/chapters/{cid}/content").json()["revision_no"] == 1
    acc = client.post(f"/api/projects/{pid}/proposals/{prop['id']}/accept", json={"expected_head_no": 1})
    assert acc.json()["save"]["content"]["revision_no"] == 2
    old = client.get(f"/api/projects/{pid}/chapters/{cid}/revisions/1").json()
    assert old["source_md"] == "The engine was examined carefully by the technician.\n"  # original still accessible


def test_style_rewrite_needs_a_guide(client: TestClient) -> None:
    pid, cid, prov = setup_book(client, "Text here.\n")
    p = profile(client)
    r = client.post(
        f"/api/projects/{pid}/ai/jobs",
        json={
            "chapter_id": cid,
            "task": "revise",
            "mode": "replace_selection",
            "selection_start": 0,
            "selection_end": 4,
            "base_revision_no": 1,
            "provider_id": prov,
            "model_name": "mock-writer",
            "voice_profile_id": p["id"],
            "client_request_id": uuid.uuid4().hex,
        },
    )
    assert r.status_code == 409


# ---------- interview ----------


def test_answers_are_exact_versioned_and_immutable(client: TestClient, ctx: AppContext) -> None:
    pid, _, _ = setup_book(client)
    iv = client.get(f"/api/projects/{pid}/interview").json()
    assert len(iv["questions"]) == 10 and iv["answered"] == 0
    q = iv["questions"][0]
    exact = "My grandfather's shed, 1998.  Two spaces, a typo: teh spanner — and an em dash."
    iv = client.put(f"/api/projects/{pid}/interview/questions/{q['id']}/answer", json={"answer_text": exact}).json()
    assert iv["questions"][0]["answer"]["answer_text"] == exact and iv["answered"] == 1
    iv = client.put(
        f"/api/projects/{pid}/interview/questions/{q['id']}/answer", json={"answer_text": exact + " More."}
    ).json()
    first, second = iv["questions"][0]["history"]
    assert second["supersedes_id"] == first["id"] and first["answer_text"] == exact
    with pytest.raises(Exception, match="immutable"), ctx.db.tx() as s:
        s.execute(text("UPDATE interview_answer SET answer_text = 'changed'"))
    custom = client.post(
        f"/api/projects/{pid}/interview/questions", json={"prompt": "What was your first engine?"}
    ).json()
    assert custom["questions"][-1]["origin"] == "author"


def test_drafting_from_interview_uses_only_the_authors_words(
    client: TestClient, runner: JobRunner, captured: list[GenRequest]
) -> None:
    pid, cid, prov = setup_book(client)
    iv = client.get(f"/api/projects/{pid}/interview").json()
    q = iv["questions"][0]
    answer = "I rebuilt my first carburettor at fourteen in my grandfather's shed."
    client.put(f"/api/projects/{pid}/interview/questions/{q['id']}/answer", json={"answer_text": answer})
    ask(client, pid, cid, prov, instruction="Open with how I started on carburettors.", use_interview=True)
    runner.run_until_idle()
    sent = captured[-1].messages[-1].content
    assert 'label="interview answer I1"' in sent and "never invent or embellish a personal experience" in sent
    p = proposal(client, pid)
    para = next(x for x in p["provenance"]["knowledge"]["paragraphs"] if x["supports"])
    sup = para["supports"][0]
    assert sup["kind"] == "interview" and sup["located"] is True and sup["quote"] == answer
    assert "[[I1]]" not in p["payload_md"] and "@" not in p["payload_md"]  # no bibliography key for an interview
    # Without interview answers the model is told not to invent personal experiences.
    ask(client, pid, cid, prov, instruction="Open with a story.")
    runner.run_until_idle()
    assert "Do not invent personal experiences" in captured[-1].messages[-1].content


# ---------- backup and restore of citations ----------


def test_backup_restore_keeps_citations_sources_claims_and_answers(client: TestClient, runner: JobRunner) -> None:
    pid, cid, prov = setup_book(client)
    upload(client, pid, "torque-handbook.md", HANDBOOK)
    ask(client, pid, cid, prov)
    runner.run_until_idle()
    prop = proposal(client, pid)
    client.post(f"/api/projects/{pid}/proposals/{prop['id']}/accept", json={"expected_head_no": 1})
    hit = client.get(f"/api/projects/{pid}/knowledge/search", params={"q": "wheel nuts"}).json()["hits"][0]
    client.post(f"/api/projects/{pid}/claims", json={"text": "Wheel nuts: 80-110 Nm.", "chunk_ids": [hit["chunk_id"]]})
    q = client.get(f"/api/projects/{pid}/interview").json()["questions"][0]
    client.put(f"/api/projects/{pid}/interview/questions/{q['id']}/answer", json={"answer_text": "My exact words."})
    text_before = client.get(f"/api/projects/{pid}/chapters/{cid}/content").json()["source_md"]
    assert "[@torque-handbook, para" in text_before

    backup = client.post(f"/api/projects/{pid}/backups").json()
    blob = client.get(f"/api/backups/{backup['id']}/file").content
    restored = client.post(
        "/api/backups/restore", files={"file": ("b.zip", io.BytesIO(blob), "application/zip")}
    ).json()
    assert restored["sources"] == 1 and restored["claims"] == 2
    rp = restored["project"]["id"]
    rch = client.get(f"/api/projects/{rp}/chapters").json()[0]["id"]
    assert client.get(f"/api/projects/{rp}/chapters/{rch}/content").json()["source_md"] == text_before
    assert [c["id"] for c in client.get(f"/api/projects/{rp}/citations").json()] == ["torque-handbook"]
    ledger = client.get(f"/api/projects/{rp}/claims").json()
    assert len(ledger) == 2 and all(c["supports"] and c["supports"][0]["chunk_id"] for c in ledger)
    assert {c["support_status"] for c in ledger} == {"supported"}
    assert client.get(f"/api/projects/{rp}/knowledge/search", params={"q": "spiral"}).json()["hits"]  # index rebuilt
    ans = client.get(f"/api/projects/{rp}/interview").json()["questions"][0]["answer"]
    assert ans["answer_text"] == "My exact words."
    # The original book is untouched and still separate.
    assert len(client.get(f"/api/projects/{pid}/claims").json()) == 2
