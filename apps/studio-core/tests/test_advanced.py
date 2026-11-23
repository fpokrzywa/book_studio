"""Phase 08: series canon and continuity, pen names, translated editions, narration and recorded interviews."""

from __future__ import annotations

import io
import json
import struct
import wave
import zipfile
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from pbs_core.context import AppContext
from pbs_core.jobs.runner import JobRunner
from pbs_core.media import engines, narration
from pbs_core.providers import egress
from pbs_core.providers.base import GenRequest
from pbs_core.storage.ai_models import Job
from tests.conftest import new_chapter, new_project, save
from tests.test_planning import mock_provider, rid

CANARY = "sk-canary-phase08-000000000000"


def ok(r: Any, code: int = 200) -> Any:
    assert r.status_code == code, r.text
    return r.json()


def wav(ms: int = 1200, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(rate * ms / 1000))
    return buf.getvalue()


def book(client: TestClient, title: str, text: str, chapter: str = "Chapter One") -> tuple[str, str]:
    pid = new_project(client, title=title, project_type="fiction")["id"]
    cid = new_chapter(client, pid, chapter)["id"]
    assert save(client, pid, cid, text, 0).status_code == 200
    return pid, cid


def series_with_two_books(client: TestClient) -> tuple[str, str, str, str, str]:
    b1, c1 = book(client, "The Salt Road", "Mara looked up. Mara's green eyes caught the lamp.\n")
    b2, c2 = book(client, "The Iron Tide", "Years later, Mara turned. Mara's brown eyes were wet.\n")
    sid = ok(client.post("/api/series", json={"title": "Tides of Salt"}), 201)["id"]
    ok(client.post(f"/api/series/{sid}/books", json={"project_id": b1}))
    out = ok(client.post(f"/api/series/{sid}/books", json={"project_id": b2}))
    assert [b["title"] for b in out["books"]] == ["The Salt Road", "The Iron Tide"]
    return sid, b1, c1, b2, c2


# ---------- acceptance: two books, shared canon, an intentional contradiction, user resolution ----------


def test_series_canon_contradiction_and_resolution_survive_rerun(client: TestClient) -> None:
    sid, b1, _c1, b2, c2 = series_with_two_books(client)
    mara = ok(
        client.post(f"/api/series/{sid}/entities", json={"kind": "character", "name": "Mara", "aliases": ["Mar"]}), 201
    )
    fact = ok(client.post(f"/api/series/{sid}/facts", json={"entity_id": mara["id"], "attribute": "eye colour",
                                                             "value": "grey", "book_project_id": b1}), 201)  # fmt: skip
    assert fact["status"] == "canon" and fact["origin"] == "author"
    # Modify canon: the author corrects the eye colour. The old row is kept and points at its replacement.
    fixed = ok(client.patch(f"/api/series/{sid}/facts/{fact['id']}", json={"value": "green"}))
    canon = ok(client.get(f"/api/series/{sid}/canon"))
    facts = canon["entities"][0]["facts"]
    old = next(f for f in facts if f["id"] == fact["id"])
    assert old["superseded_by"] == fixed["id"] and fixed["value"] == "green"

    # Book 2 contradicts canon on purpose ("brown eyes").
    rv = ok(client.post(f"/api/series/{sid}/review", json={}))
    assert rv["checked_chapters"] == 2 and rv["new"] == 1
    issue = rv["issues"][0]
    assert issue["rule"] == "trait" and issue["project_id"] == b2 and issue["found_value"] == "brown"
    assert issue["link"] == f"/projects/{b2}/chapters/{c2}?select={issue['start']}-{issue['end']}"
    text = ok(client.get(f"/api/projects/{b2}/chapters/{c2}/content"))["source_md"]
    assert "brown eyes" in text[issue["start"] : issue["end"]]

    # The author decides it is intended (a lie, a dye, a lens); a re-run keeps that decision.
    res = ok(
        client.post(
            f"/api/series/{sid}/issues/{issue['id']}/resolve", json={"action": "intended", "note": "Contact lenses."}
        )
    )
    assert res["state"] == "intended"
    again = ok(client.post(f"/api/series/{sid}/review", json={}))
    assert again["new"] == 0
    kept = next(i for i in again["issues"] if i["id"] == issue["id"])
    assert kept["state"] == "intended" and kept["resolution_note"] == "Contact lenses." and kept["present"]
    # The manuscript was not touched by the review.
    assert ok(client.get(f"/api/projects/{b2}/chapters/{c2}"))["head_revision_no"] == 1

    # Reopen, then take the book's value into canon: canon changes, the finding disappears on the next run.
    ok(client.post(f"/api/series/{sid}/issues/{issue['id']}/resolve", json={"action": "reopen"}))
    upd = ok(client.post(f"/api/series/{sid}/issues/{issue['id']}/resolve", json={"action": "update_canon"}))
    assert upd["state"] == "canon_updated"
    current = [
        f for f in ok(client.get(f"/api/series/{sid}/canon"))["entities"][0]["facts"] if f["superseded_by"] is None
    ]
    assert [f["value"] for f in current] == ["brown"] and current[0]["provenance"]["from_issue"] == issue["id"]
    final = ok(client.post(f"/api/series/{sid}/review", json={}))
    # Book 1 now contradicts the new canon ("green eyes"), book 2 no longer does; book 2's decision is kept.
    assert next(i for i in final["issues"] if i["id"] == issue["id"])["present"] is False
    assert any(i["project_id"] == b1 and i["found_value"] == "green" and i["present"] for i in final["issues"])


def test_relationship_check_and_suggestions_are_not_canon(client: TestClient) -> None:
    sid, _b1, _c1, b2, c2 = series_with_two_books(client)
    jon = ok(client.post(f"/api/series/{sid}/entities", json={"kind": "character", "name": "Jon"}), 201)
    mara = ok(client.post(f"/api/series/{sid}/entities", json={"kind": "character", "name": "Mara"}), 201)
    ok(client.post(f"/api/series/{sid}/relationships", json={"from_entity_id": jon["id"], "to_entity_id": mara["id"],
                                                             "label": "brother"}), 201)  # fmt: skip
    assert save(client, b2, c2, "At the dock stood Mara's cousin Jon.\n", 1).status_code == 200
    rv = ok(client.post(f"/api/series/{sid}/review", json={"project_id": b2}))
    rel = [i for i in rv["issues"] if i["rule"] == "relationship"]
    assert len(rel) == 1 and rel[0]["found_value"] == "cousin"
    # A suggested fact (not yet approved) is never compared.
    sug = ok(
        client.post(f"/api/series/{sid}/facts", json={"entity_id": mara["id"], "attribute": "age", "value": "30"}), 201
    )
    ok(client.patch(f"/api/series/{sid}/facts/{sug['id']}", json={"status": "suggested"}))
    assert save(client, b2, c2, "Mara was 45 years old.\n", 2).status_code == 200
    assert not [
        i
        for i in ok(client.post(f"/api/series/{sid}/review", json={}))["issues"]
        if i["rule"] == "age" and i["present"]
    ]


def test_series_canon_reaches_writing_prompts(client: TestClient, ctx: AppContext) -> None:
    from pbs_core.writing import memory

    sid, b1, *_ = series_with_two_books(client)
    mara = ok(client.post(f"/api/series/{sid}/entities", json={"kind": "character", "name": "Mara"}), 201)
    ok(
        client.post(
            f"/api/series/{sid}/facts", json={"entity_id": mara["id"], "attribute": "eye colour", "value": "green"}
        ),
        201,
    )
    with ctx.db.tx() as s:
        lines = memory.fact_items(s, b1)
    assert any("Mara" in str(x) and "green" in str(x) for x in lines)


# ---------- pen names and the active voice ----------


def test_pen_name_voice_rules_shown_per_project_and_used_in_prompts(
    client: TestClient, ctx: AppContext, runner: JobRunner, captured: list[GenRequest]
) -> None:
    prof = ok(client.post("/api/voice/profiles", json={"name": "Night voice"}), 201)
    out = ok(client.put(f"/api/voice/profiles/{prof['id']}/pen-name", json={
        "pen_name": "R. Vale", "voice_rules": [{"kind": "do", "rule": "Short sentences in action scenes"},
                                               {"kind": "avoid", "rule": "Adverbs ending in -ly"}]}))  # fmt: skip
    assert out["pen_name"] == "R. Vale" and len(out["voice_rules"]) == 2
    pid, _cid = book(client, "Vale Book", "Rain.\n")
    assert ok(client.get(f"/api/projects/{pid}/voice"))["author_profile_id"] is None
    active = ok(client.put(f"/api/projects/{pid}/voice", json={"author_profile_id": prof["id"]}))
    assert active["pen_name"] == "R. Vale" and active["profile_name"] == "Night voice"
    from pbs_core.services import voice

    block = voice.for_prompt(ctx, prof["id"])
    assert (
        block is not None and block["pen_name"] == "R. Vale" and "Adverbs ending in -ly" in json.dumps(block["rules"])
    )


# ---------- acceptance: translate one chapter without editing the source ----------


SOURCE = (
    "# The Harbour\n\nMara counted the boats [@smith2020]. She knew the old saying: it never rains but it pours.\n\n"
    "```python\nprint('tide')\n```\n\nThe formula $E = mc^2$ held.[^1]\n\n[^1]: A note.\n"
)


def approved_source(client: TestClient) -> tuple[str, str]:
    pid, cid = book(client, "The Salt Road", SOURCE, "The Harbour")
    ok(client.patch(f"/api/projects/{pid}/chapters/{cid}", json={"status": "approved"}))
    return pid, cid


def test_translate_one_chapter_without_touching_source(client: TestClient, runner: JobRunner) -> None:
    pid, cid = approved_source(client)
    before = ok(client.get(f"/api/projects/{pid}/chapters/{cid}"))
    before_md = ok(client.get(f"/api/projects/{pid}/chapters/{cid}/content"))["source_md"]
    prov = mock_provider(client)
    ed = ok(client.post(f"/api/projects/{pid}/editions", json={"language": "fr", "term_map": {"harbour": "port"}}), 201)
    tpid = ed["target_project_id"]
    tcid = ed["chapters"][0]["target_chapter_id"]
    assert ed["chapters"][0]["status"] == "not_started" and tpid != pid
    target = ok(client.get(f"/api/projects/{tpid}"))
    assert target["language"] == "fr"

    job = ok(client.post(f"/api/projects/{pid}/editions/{ed['id']}/translate", json={
        "source_chapter_id": cid, "source_revision_no": 1, "provider_id": prov, "model_name": "mock-writer",
        "client_request_id": rid()}), 202)  # fmt: skip
    runner.run_until_idle()
    assert ok(client.get(f"/api/ai/jobs/{job['id']}"))["status"] == "succeeded"

    # Source unchanged: same head, same text, no new revision.
    after = ok(client.get(f"/api/projects/{pid}/chapters/{cid}"))
    assert after["head_revision_no"] == before["head_revision_no"] == 1
    assert ok(client.get(f"/api/projects/{pid}/chapters/{cid}/content"))["source_md"] == before_md
    assert len(ok(client.get(f"/api/projects/{pid}/chapters/{cid}/revisions"))) == 1

    ed = ok(client.get(f"/api/projects/{pid}/editions/{ed['id']}"))
    row = ed["chapters"][0]
    assert row["status"] == "suggested" and row["source_revision_no"] == 1
    kinds = {i["kind"] for i in row["issues"]}
    assert "idiom" in kinds and "terminology" in kinds  # flagged for review, not silently "fixed"
    props = ok(client.get(f"/api/projects/{tpid}/proposals", params={"chapter_id": tcid}))
    prop = next(p for p in props if p["id"] == row["proposal_id"])
    # Protected content survives byte for byte: code, math, citation and footnote marker.
    for keep in ("print('tide')", "$E = mc^2$", "[@smith2020]", "[^1]"):
        assert keep in prop["payload_md"]
    ok(client.post(f"/api/projects/{tpid}/proposals/{prop['id']}/accept", json={"expected_head_no": 0}))
    assert ok(client.get(f"/api/projects/{tpid}/chapters/{tcid}"))["head_revision_no"] == 1
    assert ok(client.get(f"/api/projects/{pid}/chapters/{cid}/content"))["source_md"] == before_md

    # Language-specific chapter links, both ways.
    src_links = ok(client.get(f"/api/projects/{pid}/chapters/{cid}/translations"))
    assert src_links["language"] == "en" and src_links["translation_of"] is None
    assert [(t["language"], t["chapter_id"], t["status"]) for t in src_links["translations"]] == [
        ("fr", tcid, "accepted")
    ]
    tgt_links = ok(client.get(f"/api/projects/{tpid}/chapters/{tcid}/translations"))
    assert tgt_links["language"] == "fr" and tgt_links["translation_of"]["chapter_id"] == cid
    assert tgt_links["translation_of"]["link"] == f"/projects/{pid}/chapters/{cid}"
    # Same chapter identity kept across editions (slug and outline position).
    src_ch, tgt_ch = after, ok(client.get(f"/api/projects/{tpid}/chapters/{tcid}"))
    assert src_ch["slug"] == tgt_ch["slug"] and src_ch["position"] == tgt_ch["position"]


def test_translation_requires_an_approved_revision_and_rejects_lost_placeholders(
    client: TestClient, runner: JobRunner
) -> None:
    pid, cid = book(client, "Draft Book", SOURCE)
    prov = mock_provider(client)
    ed = ok(client.post(f"/api/projects/{pid}/editions", json={"language": "de"}), 201)
    body = {"source_chapter_id": cid, "source_revision_no": 1, "provider_id": prov, "model_name": "mock-writer"}
    r = client.post(f"/api/projects/{pid}/editions/{ed['id']}/translate", json={**body, "client_request_id": rid()})
    assert r.status_code == 409 and r.json()["reason"] == "not_approved"
    # A revision labelled "Approved" in history also counts.
    ok(client.put(f"/api/projects/{pid}/chapters/{cid}/revisions/1/tag", json={"label": "Approved"}))
    assert save(client, pid, cid, SOURCE + "\n[[mock:drop_code]]\n", 1).status_code == 200
    ok(client.put(f"/api/projects/{pid}/chapters/{cid}/revisions/2/tag", json={"label": "approved"}))
    job = ok(client.post(f"/api/projects/{pid}/editions/{ed['id']}/translate",
                         json={**body, "source_revision_no": 2, "client_request_id": rid()}), 202)  # fmt: skip
    for _ in range(3):  # invalid output is retried; skip the backoff wait between attempts
        runner.run_once()
        with runner.ctx.db.tx() as s:
            row = s.get(Job, job["id"])
            assert row is not None
            row.run_after = runner.ctx.clock.iso()
    runner.run_until_idle()
    j = ok(client.get(f"/api/ai/jobs/{job['id']}"))
    assert j["status"] == "failed" and j["error_code"] == "invalid_output"
    assert ok(client.get(f"/api/projects/{pid}/editions/{ed['id']}"))["chapters"][0]["proposal_id"] is None
    # Editions of editions and duplicate languages are refused.
    assert client.post(f"/api/projects/{pid}/editions", json={"language": "de"}).status_code == 409
    assert client.post(f"/api/projects/{ed['target_project_id']}/editions", json={"language": "fr"}).status_code == 409
    assert client.post(f"/api/projects/{pid}/editions", json={"language": "en"}).status_code == 422


# ---------- narration ----------


def test_narration_chunks_keep_alignment_and_announce_unreadable_content() -> None:
    from pbs_core.document import bookmd

    n = iter(range(10_000))
    doc = bookmd.parse(SOURCE * 3, chapter_id="c", new_id=lambda: f"b{next(n)}").doc
    chunks = narration.chunk(doc, "The Harbour", max_chars=200)
    assert all(len(c.text) <= 200 for c in chunks)
    assert chunks[0].text.startswith("The Harbour.")
    joined = " ".join(c.text for c in chunks)
    assert "A code listing appears here in the book." in joined and "print(" not in joined
    assert "@smith2020" not in joined
    assert all(c.block_ids for c in chunks)
    assert any("Code listing announced" in n for c in chunks for n in c.notes)


def test_narration_degrades_gracefully_without_an_engine(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engines, "_which", lambda *names: None)
    pid, cid = book(client, "Quiet Book", "It was late. The tide turned.\n")
    ov = ok(client.get(f"/api/projects/{pid}/narration"))
    assert ov["settings"]["enabled"] is False
    espeak = next(p for p in ov["providers"] if p["kind"] == "espeak")
    assert espeak["available"] is False and "Not installed" in espeak["reason"]
    # Synthesis is off by default: nothing runs.
    r = client.post(f"/api/projects/{pid}/narration/chapters/{cid}/synthesize")
    assert r.status_code == 409 and r.json()["reason"] == "disabled"
    ok(client.put(f"/api/projects/{pid}/narration/settings", json={"enabled": True, "provider": "espeak"}))
    # The script is still prepared (no engine needed) ...
    sc = ok(client.post(f"/api/projects/{pid}/narration/chapters/{cid}/prepare"))
    assert sc["chunks"] >= 1 and sc["items"][0]["text"].startswith("Chapter One.")
    # ... but synthesis says plainly that the engine is missing.
    r = client.post(f"/api/projects/{pid}/narration/chapters/{cid}/synthesize")
    assert r.status_code == 409 and r.json()["reason"] == "unavailable"
    assert client.post(f"/api/projects/{pid}/narration/export").status_code == 409
    st = ok(client.get("/api/media/status"))
    assert {t["name"]: t["status"] for t in st["optional_tools"]}["whisper"] == "not installed"


def test_narration_with_test_engine_exports_aligned_audio(client: TestClient) -> None:
    pid, cid = book(client, "Loud Book", "# Opening\n\nThe gulls cried. The rope creaked.\n\n```\ncode\n```\n")
    ok(client.put(f"/api/projects/{pid}/narration/settings",
                  json={"enabled": True, "provider": "mock", "max_chunk_chars": 200}))  # fmt: skip
    ok(client.post(f"/api/projects/{pid}/narration/chapters/{cid}/prepare"))
    out = ok(client.post(f"/api/projects/{pid}/narration/chapters/{cid}/synthesize?limit=50"))
    assert out["done"] == out["total"] >= 1 and out["failed"] == 0
    sc = ok(client.get(f"/api/projects/{pid}/narration/chapters/{cid}"))
    part = sc["items"][0]
    assert part["has_audio"] and part["cost"] == "0"
    a = client.get(f"/api/projects/{pid}/narration/parts/{part['id']}/audio")
    assert a.status_code == 200 and a.content[:4] == b"RIFF"
    ex = ok(client.post(f"/api/projects/{pid}/narration/export"), 201)
    assert "Not checked against ACX/Audible" in ex["notes"] and "AI-generated" in ex["notes"]
    assert "test engine" in ex["notes"]
    f = client.get(f"/api/projects/{pid}/narration/exports/{ex['file_name']}")
    assert f.status_code == 200
    with zipfile.ZipFile(io.BytesIO(f.content)) as z:
        names = z.namelist()
        meta = json.loads(z.read("chapters.json"))
    assert {"chapters.json", "book.cue", "NOTES.txt"} <= set(names) and any(n.endswith(".wav") for n in names)
    ch = meta["chapters"][0]
    assert ch["chapter_id"] == cid and ch["parts"][0]["start_ms"] == 0 and ch["parts"][0]["block_ids"]
    # A new revision makes the old audio stale rather than silently reusing it.
    assert save(client, pid, cid, "# Opening\n\nChanged.\n", 1).status_code == 200
    row = ok(client.get(f"/api/projects/{pid}/narration"))["chapters"][0]
    assert row["chunks"] == 0 and row["older_revision_audio"] is True
    assert client.get(f"/api/projects/{pid}/narration/exports/..%2Fsecret.zip").status_code == 404


def _openai_provider(client: TestClient) -> str:
    prov = ok(client.post("/api/ai/providers", json={"kind": "openai"}), 201)
    assert client.put(f"/api/ai/providers/{prov['id']}/key", json={"api_key": CANARY}).status_code == 200
    return prov["id"]  # type: ignore[no-any-return]


def test_local_only_mode_blocks_cloud_speech_and_transcription(client: TestClient, ctx: AppContext) -> None:
    sent: list[Any] = []
    ctx.http_transport = httpx2.MockTransport(lambda r: sent.append(r) or httpx2.Response(200, content=wav()))
    prov = _openai_provider(client)
    pid, cid = book(client, "Private Book", "Secret words.\n")
    ok(
        client.put(
            f"/api/projects/{pid}/narration/settings",
            json={"enabled": True, "provider": "openai", "openai_provider_id": prov},
        )
    )
    ok(client.post(f"/api/projects/{pid}/narration/chapters/{cid}/prepare"))
    before = egress.external_requests()
    r = client.post(f"/api/projects/{pid}/narration/chapters/{cid}/synthesize")
    assert r.status_code == 409 and "Local-only" in r.json()["title"]
    rec = ok(client.post(f"/api/projects/{pid}/recordings", files={"file": ("talk.wav", wav(), "audio/wav")},
                         data={"rights_confirmed": "true", "title": "Talk"}), 201)  # fmt: skip
    r = client.post(
        f"/api/projects/{pid}/recordings/{rec['id']}/transcribe",
        json={"provider": "openai", "openai_provider_id": prov},
    )
    assert r.status_code == 409 and "Local-only" in r.json()["title"]
    assert sent == [] and egress.external_requests() == before
    assert all(not p["available"] for p in ok(client.get("/api/media/status"))["speech"] if not p["local"])


def test_cloud_speech_and_transcription_when_allowed(client: TestClient, ctx: AppContext) -> None:
    seen: list[httpx2.Request] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(req)
        if req.url.path.endswith("/audio/speech"):
            body = json.loads(req.content)
            assert body["response_format"] == "wav" and len(body["input"]) <= 4096
            return httpx2.Response(200, content=wav(800))
        assert req.url.path.endswith("/audio/transcriptions")
        return httpx2.Response(200, json={"text": "Hello there. Yes.", "segments": [
            {"id": 0, "start": 0.0, "end": 1.5, "text": " Hello there."},
            {"id": 1, "start": 1.5, "end": 2.4, "text": " Yes."}]})  # fmt: skip

    ctx.http_transport = httpx2.MockTransport(handler)
    prov = _openai_provider(client)
    pid, cid = book(client, "Open Book", "The lamp was lit.\n")
    ok(client.put("/api/ai/privacy", json={"mode": "cloud_allowed", "confirm": True}))
    ok(client.put(f"/api/projects/{pid}/narration/settings", json={"enabled": True, "provider": "openai", "openai_provider_id": prov,
                                                                    "voice": "marin", "price_per_million_chars": "15", "currency": "USD"}))  # fmt: skip
    ok(client.post(f"/api/projects/{pid}/narration/chapters/{cid}/prepare"))
    r = client.post(f"/api/projects/{pid}/narration/chapters/{cid}/synthesize")
    assert r.status_code == 409 and "not been allowed" in r.json()["title"] and not seen  # no project consent yet
    ok(client.put(f"/api/projects/{pid}/ai/consent/{prov}"))
    out = ok(client.post(f"/api/projects/{pid}/narration/chapters/{cid}/synthesize"))
    assert out["done"] == out["total"]
    part = ok(client.get(f"/api/projects/{pid}/narration/chapters/{cid}"))["items"][0]
    assert part["cost"] == str((15 * len(part["text"]) / 1_000_000).__format__(".6f"))
    assert seen[0].headers["authorization"] == f"Bearer {CANARY}"

    rec = ok(client.post(f"/api/projects/{pid}/recordings", files={"file": ("talk.wav", wav(2500), "audio/wav")},
                         data={"rights_confirmed": "true"}), 201)  # fmt: skip
    t = ok(client.post(f"/api/projects/{pid}/recordings/{rec['id']}/transcribe",
                       json={"provider": "openai", "openai_provider_id": prov, "model": "whisper-1"}))  # fmt: skip
    assert [(g["start_ms"], g["end_ms"], g["text"]) for g in t["segments"]] == [
        (0, 1500, "Hello there."),
        (1500, 2400, "Yes."),
    ]
    assert b"verbose_json" in seen[-1].content
    # The secret never lands in the database, logs or files the app writes.
    assert CANARY.encode() not in ctx.workspace.db_path.read_bytes()


# ---------- recorded interviews ----------


def test_recording_rights_transcript_speakers_and_quote_as_source(client: TestClient, ctx: AppContext) -> None:
    pid, _cid = book(client, "Interview Book", "Notes.\n")
    r = client.post(f"/api/projects/{pid}/recordings", files={"file": ("a.wav", wav(), "audio/wav")})
    assert r.status_code == 422  # rights must be confirmed
    r = client.post(
        f"/api/projects/{pid}/recordings",
        files={"file": ("a.txt", b"hello", "text/plain")},
        data={"rights_confirmed": "true"},
    )
    assert r.status_code == 422  # not audio
    rec = ok(client.post(f"/api/projects/{pid}/recordings", files={"file": ("chat.wav", wav(3000), "audio/wav")},
                         data={"rights_confirmed": "true", "title": "Harbour master",
                               "rights_note": "Recorded with consent, 2026-11-01."}), 201)  # fmt: skip
    assert rec["duration_ms"] == 3000 and rec["status"] == "imported" and rec["segments"] == []
    t = ok(client.post(f"/api/projects/{pid}/recordings/{rec['id']}/transcribe", json={"provider": "mock"}))
    segs = t["segments"]
    assert t["status"] == "transcribed" and len(segs) == 3 and all("not real speech" in g["text"] for g in segs)
    assert segs[0]["speaker"] == "Speaker A" and segs[0]["provider_speaker"] == "A"

    # Speaker correction for every segment with the same label; text and timestamps stay as transcribed.
    t = ok(client.put(f"/api/projects/{pid}/recordings/{rec['id']}/segments/{segs[0]['id']}/speaker",
                      json={"speaker": "Ana Ruiz", "all_with_label": True}))  # fmt: skip
    assert [g["speaker"] for g in t["segments"]] == ["Ana Ruiz", "Speaker B", "Ana Ruiz"]
    from sqlalchemy import text

    with pytest.raises(Exception, match=r"immutable|transcript"), ctx.db.tx() as s:
        s.execute(text("UPDATE transcript_segment SET text='made up' WHERE id=:i"), {"i": segs[0]["id"]})

    q = ok(
        client.post(
            f"/api/projects/{pid}/recordings/{rec['id']}/quotes", json={"segment_ids": [segs[0]["id"], segs[1]["id"]]}
        ),
        201,
    )
    src = q["source"]
    assert src["id"] and all(g["source_id"] == src["id"] for g in q["recording"]["segments"][:2])
    assert q["recording"]["segments"][2]["source_id"] is None
    # Transcribing again would orphan quotations: refused.
    assert (
        client.post(f"/api/projects/{pid}/recordings/{rec['id']}/transcribe", json={"provider": "mock"}).status_code
        == 409
    )
    a = client.get(f"/api/projects/{pid}/recordings/{rec['id']}/audio")
    assert a.status_code == 200 and a.content[:4] == b"RIFF"


def test_transcription_degrades_gracefully_without_whisper(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engines, "_which", lambda *names: None)
    pid, _ = book(client, "No Tools", "x\n")
    rec = ok(client.post(f"/api/projects/{pid}/recordings", files={"file": ("a.wav", wav(), "audio/wav")},
                         data={"rights_confirmed": "true"}), 201)  # fmt: skip
    r = client.post(f"/api/projects/{pid}/recordings/{rec['id']}/transcribe", json={"provider": "whisper_cli"})
    assert r.status_code == 409 and r.json()["reason"] == "unavailable"
    assert ok(client.get(f"/api/projects/{pid}/recordings/{rec['id']}"))["status"] == "imported"
