"""Phase 08 service: optional narration and recorded interviews.

Nothing here runs a speech or transcription engine unless the author turned it on and picked one.
Without an engine the narration script (speech-ready chunks) is still prepared and exportable.
The cloud engine (OpenAI) needs cloud mode, the book's permission and a key; local-only mode refuses
it before any request is built. Transcripts are kept as the engine returned them (the text and
timestamps are immutable in the database); only speaker names can be corrected.
"""

from __future__ import annotations

import io
import json
import re
import wave
import zipfile
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.contracts_advanced import (
    AudioExportOut,
    MediaStatusOut,
    NarrationOut,
    NarrationSettingsIn,
    QuoteIn,
    RecordingOut,
    SpeakerIn,
    SynthesizeOut,
    TranscribeIn,
)
from pbs_core.domain.errors import ConflictError, NotFoundError, ValidationFailedError
from pbs_core.media import engines, narration
from pbs_core.providers import registry
from pbs_core.providers.egress import EgressPermit, cloud_activity
from pbs_core.services import activity
from pbs_core.services.imports import _store_original
from pbs_core.services.projects import require_active, require_project
from pbs_core.storage.advanced_models import NarrationChunk, Recording, TranscriptSegment
from pbs_core.storage.ai_models import ProviderConfig
from pbs_core.storage.models import AppSetting, Chapter, ChapterRevision, OriginalFile
from pbs_core.storage.paths import atomic_write_bytes, safe_join, slugify

NOTE = (
    "Narration is optional and off by default. The script below is prepared on this computer; audio is made only by "
    "the engine you choose. " + engines.NOT_ACX
)
AUDIO_MAGIC = (
    (b"RIFF", "audio/wav"),
    (b"ID3", "audio/mpeg"),
    (b"\xff\xfb", "audio/mpeg"),
    (b"\xff\xf3", "audio/mpeg"),
    (b"fLaC", "audio/flac"),
    (b"OggS", "audio/ogg"),
    (b"\x1a\x45\xdf\xa3", "audio/webm"),
)
_EXPORT_NAME = re.compile(r"^[a-z0-9-]{1,80}-audio-\d{8}T\d{6}\.zip$")


def _dev(ctx: AppContext) -> bool:
    return ctx.settings.env != "prod"


# ---------- engines and status ----------


def media_status(ctx: AppContext) -> MediaStatusOut:
    tools = []
    for name, purpose in (
        ("espeak-ng", "Speech on this computer (narration)"),
        ("piper", "Speech on this computer (narration; also set PBS_PIPER_MODEL)"),
        ("whisper", "Transcription on this computer (openai-whisper command line)"),
        ("ffmpeg", "Needed by Whisper to read MP3, M4A and other compressed audio"),
    ):
        found = engines._which(name, "espeak") if name == "espeak-ng" else engines._which(name)
        tools.append({"name": name, "purpose": purpose, "status": "found" if found else "not installed"})
    return MediaStatusOut(
        speech=_with_privacy(ctx, engines.speech_engines(_dev(ctx))),
        transcription=_with_privacy(ctx, engines.transcription_engines(_dev(ctx))),
        privacy_mode=registry.privacy_mode(ctx),
        optional_tools=tools,
    )


def _with_privacy(ctx: AppContext, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    local_only = registry.privacy_mode(ctx) != "cloud_allowed"
    for r in rows:
        if not r["local"] and local_only:
            r["available"], r["reason"] = False, "Local-only mode is on: cloud engines are blocked."
    return rows


def _openai(ctx: AppContext, provider_id: str | None, project_id: str) -> tuple[ProviderConfig, EgressPermit, str]:
    """The OpenAI provider, its permit and key, or a clear refusal before anything is sent.

    Call outside an open transaction: the permit check reads settings in its own.
    """
    if not provider_id:
        raise ConflictError("Choose the OpenAI provider to use (AI settings). Nothing was sent.")
    with ctx.db.tx() as s:
        provider = s.get(ProviderConfig, provider_id)
        if provider is None or provider.kind != "openai":
            raise ConflictError("That provider is not an OpenAI provider. Nothing was sent.")
        if not provider.enabled:
            raise ConflictError(f"{provider.label} is turned off in AI settings. Nothing was sent.")
        s.expunge(provider)
    permit = registry.permit_for(ctx, provider, project_id=project_id)
    if not permit.cloud_allowed:
        raise ConflictError(permit.reason_if_blocked or "Cloud use is not allowed. Nothing was sent.")
    key, _ = registry.api_key(ctx, provider)
    if not key:
        raise ConflictError(f"{provider.label} has no API key. Nothing was sent.")
    return provider, permit, key


def _engine_ready(ctx: AppContext, kind: str, rows: list[dict[str, Any]]) -> None:
    row = next((r for r in rows if r["kind"] == kind), None)
    if row is None:
        raise ConflictError(f"The {kind} engine is not offered here.", extra={"reason": "unavailable"})
    if row["local"] and not row["available"]:
        raise ConflictError(row["reason"] or f"{row['label']} is not installed.", extra={"reason": "unavailable"})


# ---------- narration settings ----------


def _settings_key(project_id: str) -> str:
    return f"narration:{project_id}"


def _settings(s: Session, project_id: str) -> dict[str, Any]:
    row = s.get(AppSetting, _settings_key(project_id))
    base = NarrationSettingsIn().model_dump()
    if row is not None:
        base.update(json.loads(row.value_json))
    return base


def set_settings(ctx: AppContext, project_id: str, data: NarrationSettingsIn) -> NarrationOut:
    with ctx.db.tx() as s:
        require_active(s, project_id)
        if data.provider == "mock" and not _dev(ctx):
            raise ValidationFailedError("The test engine is only for development and tests.")
        if data.provider == "openai" and data.openai_provider_id:
            p = s.get(ProviderConfig, data.openai_provider_id)
            if p is None or p.kind != "openai":
                raise ValidationFailedError("Choose an OpenAI provider from AI settings.")
        key = _settings_key(project_id)
        row = s.get(AppSetting, key)
        value = json.dumps(data.model_dump())
        if row is None:
            s.add(AppSetting(key=key, value_json=value))
        else:
            row.value_json = value
    return overview(ctx, project_id)


# ---------- narration chunks ----------


def _chapters(s: Session, project_id: str) -> list[Chapter]:
    return list(
        s.scalars(
            select(Chapter)
            .where(Chapter.project_id == project_id, Chapter.archived_at.is_(None))
            .order_by(Chapter.position, Chapter.id)
        )
    )


def _chunks(s: Session, revision_id: str) -> list[NarrationChunk]:
    return list(
        s.scalars(
            select(NarrationChunk).where(NarrationChunk.revision_id == revision_id).order_by(NarrationChunk.ordinal)
        )
    )


def _chapter_row(s: Session, ch: Chapter) -> dict[str, Any]:
    chunks = _chunks(s, ch.head_revision_id) if ch.head_revision_id else []
    older = s.scalars(
        select(NarrationChunk.id)
        .where(NarrationChunk.chapter_id == ch.id, NarrationChunk.revision_no < ch.head_revision_no)
        .limit(1)
    ).first()
    done = [c for c in chunks if c.status == "done"]
    costs = [c.cost_amount for c in done]
    return {
        "chapter_id": ch.id, "title": ch.title, "revision_no": ch.head_revision_no,
        "chunks": len(chunks), "done": len(done), "failed": sum(1 for c in chunks if c.status == "failed"),
        "duration_ms": sum(c.duration_ms or 0 for c in done),
        "chars": sum(len(c.text) for c in chunks),
        "notes": sum(len(json.loads(c.notes_json)) for c in chunks),
        "older_revision_audio": older is not None,
        "cost": _sum_cost(costs) if costs else None,
    }  # fmt: skip


def _sum_cost(costs: list[str | None]) -> str:
    if any(c is None for c in costs):
        return "unknown"
    return str(sum((Decimal(c) for c in costs if c is not None), Decimal(0)))


def overview(ctx: AppContext, project_id: str) -> NarrationOut:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        st = _settings(s, project_id)
        chapters = [_chapter_row(s, ch) for ch in _chapters(s, project_id)]
    return NarrationOut(
        settings=st, providers=_with_privacy(ctx, engines.speech_engines(_dev(ctx))), chapters=chapters, note=NOTE
    )


def _require_chapter(s: Session, project_id: str, chapter_id: str) -> Chapter:
    ch = s.get(Chapter, chapter_id)
    if ch is None or ch.project_id != project_id or ch.archived_at is not None:
        raise NotFoundError("Chapter not found.")
    return ch


def prepare(ctx: AppContext, project_id: str, chapter_id: str) -> dict[str, Any]:
    """Make the speech-ready script for the chapter's current revision (idempotent; no engine needed)."""
    with ctx.db.tx() as s:
        require_active(s, project_id)
        ch = _require_chapter(s, project_id, chapter_id)
        if not ch.head_revision_id:
            raise ConflictError("This chapter has no saved text yet.")
        if not _chunks(s, ch.head_revision_id):
            rev = s.get(ChapterRevision, ch.head_revision_id)
            if rev is None:
                raise NotFoundError("The chapter's current revision is missing.")
            st = _settings(s, project_id)
            limit = int(st.get("max_chunk_chars") or 1500)
            if st.get("provider") == "openai":
                limit = min(limit, engines.OPENAI_SPEECH_MAX_CHARS)
            now = ctx.clock.iso()
            for i, c in enumerate(narration.chunk(json.loads(rev.bdm_json), ch.title, limit), start=1):
                s.add(NarrationChunk(
                    id=ctx.ids.new(), project_id=project_id, chapter_id=ch.id, revision_id=rev.id, revision_no=rev.revision_no,
                    ordinal=i, block_ids_json=json.dumps(c.block_ids), text=c.text, notes_json=json.dumps(c.notes, ensure_ascii=False),
                    status="pending", created_at=now, updated_at=now,
                ))  # fmt: skip
            s.flush()
        return script(s, ch)


def script(s: Session, ch: Chapter) -> dict[str, Any]:
    chunks = _chunks(s, ch.head_revision_id) if ch.head_revision_id else []
    return {
        **_chapter_row(s, ch),
        "items": [
            {"id": c.id, "ordinal": c.ordinal, "text": c.text, "block_ids": json.loads(c.block_ids_json),
             "notes": json.loads(c.notes_json), "status": c.status, "provider": c.provider, "voice": c.voice,
             "duration_ms": c.duration_ms, "cost": c.cost_amount if c.status == "done" else None, "error": c.error,
             "has_audio": bool(c.audio_path)}
            for c in chunks
        ],
    }  # fmt: skip


def get_script(ctx: AppContext, project_id: str, chapter_id: str) -> dict[str, Any]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        return script(s, _require_chapter(s, project_id, chapter_id))


def _cost(st: dict[str, Any], kind: str, chars: int) -> str | None:
    if kind in ("mock", "espeak", "piper"):
        return "0"  # runs on this computer: no per-character fee
    price = st.get("price_per_million_chars") or ""
    if not price:
        return None  # unknown: the author has not entered the provider's current price
    try:
        return str((Decimal(price) * chars / Decimal(1_000_000)).quantize(Decimal("0.000001")))
    except InvalidOperation:
        return None


def synthesize(ctx: AppContext, project_id: str, chapter_id: str, limit: int = 5) -> SynthesizeOut:
    """Make audio for the next `limit` pending chunks of the chapter's current revision."""
    with ctx.db.tx() as s:
        require_active(s, project_id)
        ch = _require_chapter(s, project_id, chapter_id)
        st = _settings(s, project_id)
        if not st.get("enabled"):
            raise ConflictError(
                "Narration is off for this book. Turn it on and choose an engine first.", extra={"reason": "disabled"}
            )
        kind = st.get("provider") or ""
        if not kind:
            raise ConflictError("Choose a speech engine first.", extra={"reason": "unavailable"})
        _engine_ready(ctx, kind, engines.speech_engines(_dev(ctx)))
        if not ch.head_revision_id or not _chunks(s, ch.head_revision_id):
            raise ConflictError("Prepare the narration script for this chapter first.")
        todo = [
            (c.id, c.ordinal, c.text, c.revision_no) for c in _chunks(s, ch.head_revision_id) if c.status != "done"
        ][: max(1, limit)]
    permit = key = None
    base_url = "https://api.openai.com/v1"
    if kind == "openai":
        provider, permit, key = _openai(ctx, st.get("openai_provider_id"), project_id)
        base_url = provider.base_url or base_url
    failed = 0
    for cid, ordinal, text, rev_no in todo:
        try:
            with cloud_activity("openai", kind != "openai"):
                audio = engines.speak(kind, text, voice=st.get("voice") or "", model=st.get("model") or "", permit=permit,
                                      api_key=key, base_url=base_url, transport=ctx.http_transport)  # fmt: skip
        except engines.EngineError as exc:
            if exc.code in ("blocked", "unavailable", "auth"):
                raise ConflictError(exc.message, extra={"reason": exc.code}) from exc
            failed += 1
            with ctx.db.tx() as s:
                c = s.get(NarrationChunk, cid)
                if c is not None:
                    c.status, c.error, c.provider, c.updated_at = "failed", exc.message[:500], kind, ctx.clock.iso()
            continue
        rel = f"narration/{project_id}/{chapter_id}/r{rev_no}-{ordinal:04d}.wav"
        atomic_write_bytes(safe_join(ctx.workspace.root, rel), audio)
        with ctx.db.tx() as s:
            c = s.get(NarrationChunk, cid)
            if c is not None:
                c.status, c.error, c.provider, c.voice, c.audio_path = "done", None, kind, st.get("voice") or None, rel
                c.duration_ms, c.cost_amount, c.updated_at = (
                    engines.wav_duration_ms(audio),
                    _cost(st, kind, len(text)),
                    ctx.clock.iso(),
                )
    with ctx.db.tx() as s:
        ch = _require_chapter(s, project_id, chapter_id)
        row = _chapter_row(s, ch)
        if row["done"] == row["chunks"] and row["chunks"]:
            activity.record(s, ctx, kind="narration_ready", project_id=project_id, ref_type="chapter", ref_id=chapter_id,
                            summary=f"Narration made for “{ch.title}”")  # fmt: skip
    msg = f"{row['done']} of {row['chunks']} part(s) have audio."
    if failed:
        msg += f" {failed} failed; see each part's error and try again."
    return SynthesizeOut(
        chapter_id=chapter_id, done=row["done"], total=row["chunks"], failed=row["failed"], message=msg
    )


def chunk_audio(ctx: AppContext, project_id: str, chunk_id: str) -> Any:
    with ctx.db.tx() as s:
        c = s.get(NarrationChunk, chunk_id)
        if c is None or c.project_id != project_id or not c.audio_path:
            raise NotFoundError("No audio for this part.")
        return safe_join(ctx.workspace.root, c.audio_path)


def _join_wavs(parts: list[bytes]) -> tuple[bytes, list[int]]:
    """Concatenate WAVs with identical format. Returns the audio and each part's start offset (ms)."""
    out = io.BytesIO()
    offsets: list[int] = []
    params = None
    frames_so_far = 0
    with wave.open(out, "wb") as w:
        for data in parts:
            with wave.open(io.BytesIO(data)) as r:
                p = (r.getnchannels(), r.getsampwidth(), r.getframerate())
                if params is None:
                    params = p
                    w.setnchannels(p[0])
                    w.setsampwidth(p[1])
                    w.setframerate(p[2])
                elif p != params:
                    raise ConflictError(
                        "Parts of this chapter were made with different engines or voices. Make them again with one engine."
                    )
                offsets.append(int(frames_so_far * 1000 / p[2]))
                frames = r.readframes(r.getnframes())
                frames_so_far += r.getnframes()
                w.writeframes(frames)
    return out.getvalue(), offsets


def _ts(ms: int) -> str:
    return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


def export_audio(ctx: AppContext, project_id: str) -> AudioExportOut:
    """A ZIP with one WAV per fully narrated chapter, chapters.json (alignment), a cue sheet and NOTES.txt."""
    with ctx.db.tx() as s:
        project = require_project(s, project_id)
        st = _settings(s, project_id)
        plan = []
        for ch in _chapters(s, project_id):
            chunks = _chunks(s, ch.head_revision_id) if ch.head_revision_id else []
            if chunks and all(c.status == "done" and c.audio_path for c in chunks):
                plan.append((ch.id, ch.title, ch.slug, ch.head_revision_no,
                             [(c.ordinal, c.audio_path, json.loads(c.block_ids_json), c.provider, c.voice, c.cost_amount) for c in chunks]))  # fmt: skip
        title = project.title
    if not plan:
        raise ConflictError("No chapter has audio for every part yet. Make the narration first.")
    buf = io.BytesIO()
    meta: list[dict[str, Any]] = []
    cue = [f'TITLE "{title.replace(chr(34), chr(39))}"']
    providers, costs, book_ms = set(), [], 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, (cid, ctitle, slug, rev_no, parts) in enumerate(plan, start=1):
            datas = [safe_join(ctx.workspace.root, str(p[1])).read_bytes() for p in parts]
            audio, offsets = _join_wavs(datas)
            dur = engines.wav_duration_ms(audio) or 0
            name = f"{n:02d}-{slug}.wav"
            z.writestr(name, audio)
            meta.append({
                "track": n, "file": name, "chapter_id": cid, "title": ctitle, "revision_no": rev_no, "duration_ms": dur,
                "book_offset_ms": book_ms,
                "parts": [{"ordinal": p[0], "start_ms": off, "block_ids": p[2]} for p, off in zip(parts, offsets, strict=True)],
            })  # fmt: skip
            cue += [
                f'FILE "{name}" WAVE',
                f"  TRACK {n:02d} AUDIO",
                f'    TITLE "{ctitle.replace(chr(34), chr(39))}"',
                "    INDEX 01 00:00:00",
            ]
            book_ms += dur
            providers |= {(p[3] or "", p[4] or "") for p in parts}
            costs += [p[5] for p in parts]
        notes = _notes(title, st, providers, _sum_cost(costs), meta)
        z.writestr("chapters.json", json.dumps({"title": title, "chapters": meta}, ensure_ascii=False, indent=2))
        z.writestr("book.cue", "\n".join(cue) + "\n")
        z.writestr("NOTES.txt", notes)
    stamp = ctx.clock.now().strftime("%Y%m%dT%H%M%S")
    file_name = f"{(slugify(title) or 'book')[:60]}-audio-{stamp}.zip"
    rel = f"narration/{project_id}/exports/{file_name}"
    data = buf.getvalue()
    atomic_write_bytes(safe_join(ctx.workspace.root, rel), data)
    with ctx.db.tx() as s:
        activity.record(s, ctx, kind="audio_exported", project_id=project_id, ref_type="project", ref_id=project_id,
                        summary=f"Exported narration for {len(meta)} chapter(s) of “{title}”")  # fmt: skip
    return AudioExportOut(file_name=file_name, path=rel, bytes=len(data),
                          chapters=[{k: m[k] for k in ("track", "title", "duration_ms", "file")} for m in meta], notes=notes)  # fmt: skip


def _notes(
    title: str, st: dict[str, Any], providers: set[tuple[str, str]], cost: str, meta: list[dict[str, Any]]
) -> str:
    engines_used = ", ".join(sorted(f"{p}{' (voice ' + v + ')' if v else ''}" for p, v in providers)) or "none"
    lines = [
        f"Narration of “{title}”",
        "",
        f"Engines used: {engines_used}",
        f"Chapters: {len(meta)} (see chapters.json for each part's start time and the source blocks it reads)",
        "Format: WAV (PCM) per chapter, plus book.cue",
        "",
        "Cost",
        f"  {cost} {st.get('currency') or ''}".rstrip()
        + ("" if cost != "unknown" else "  (enter the provider's current price per million characters to estimate it)"),
        "  Local engines (eSpeak NG, Piper) run on this computer and have no per-character fee.",
        "",
        "Licensing and disclosure",
        "  " + engines.AI_VOICE_NOTICE,
        "  Check the licence of the voice you used: eSpeak NG is GPL-3.0 software; each Piper voice model has its own",
        "  licence (see its model card); OpenAI's terms and usage policies apply to OpenAI speech.",
        "  You are responsible for the rights to the text being narrated.",
        "",
        "Store requirements",
        "  " + engines.NOT_ACX,
    ]
    if "mock" in {p for p, _ in providers}:
        lines += ["", "WARNING: parts were made with the built-in test engine. They are silence, not speech."]
    return "\n".join(lines) + "\n"


def export_file(ctx: AppContext, project_id: str, file_name: str) -> Any:
    if not _EXPORT_NAME.match(file_name):
        raise NotFoundError("Export not found.")
    with ctx.db.tx() as s:
        require_project(s, project_id)
    p = safe_join(ctx.workspace.root, f"narration/{project_id}/exports/{file_name}")
    if not p.is_file():
        raise NotFoundError("Export not found.")
    return p


# ---------- recordings ----------


def _audio_mime(data: bytes) -> str | None:
    if data[4:8] == b"ftyp":
        return "audio/mp4"
    for magic, mime in AUDIO_MAGIC:
        if data.startswith(magic):
            if magic == b"RIFF" and data[8:12] != b"WAVE":
                return None
            return mime
    return None


def _rec_out(s: Session, r: Recording) -> RecordingOut:
    orig = s.get(OriginalFile, r.original_file_id)
    segs = s.scalars(
        select(TranscriptSegment).where(TranscriptSegment.recording_id == r.id).order_by(TranscriptSegment.ordinal)
    )
    return RecordingOut(
        id=r.id, title=r.title, mime=r.mime, byte_size=orig.byte_size if orig else 0, duration_ms=r.duration_ms,
        rights_note=r.rights_note, status=r.status, provider=r.provider, model=r.model, error=r.error,
        segments=[{"id": g.id, "ordinal": g.ordinal, "start_ms": g.start_ms, "end_ms": g.end_ms, "speaker": g.speaker,
                   "provider_speaker": g.provider_speaker, "text": g.text, "source_id": g.source_id} for g in segs],
        created_at=r.created_at,
    )  # fmt: skip


def _require_recording(s: Session, project_id: str, recording_id: str) -> Recording:
    r = s.get(Recording, recording_id)
    if r is None or r.project_id != project_id:
        raise NotFoundError("Recording not found.")
    return r


def import_recording(ctx: AppContext, project_id: str, filename: str, data: bytes, *, title: str, rights_confirmed: bool,
                     rights_note: str) -> RecordingOut:  # fmt: skip
    if not rights_confirmed:
        raise ValidationFailedError("Confirm that you own this recording or have the speakers' permission to use it.")
    mime = _audio_mime(data)
    if mime is None:
        raise ValidationFailedError(
            "This is not an audio file this app can store (WAV, MP3, M4A/MP4, FLAC, OGG or WebM)."
        )
    with ctx.db.tx() as s:
        require_active(s, project_id)
        orig, _ = _store_original(s, ctx, filename, data, "audio")
        r = Recording(
            id=ctx.ids.new(), project_id=project_id, original_file_id=orig.id, title=(title or filename)[:200], mime=mime,
            duration_ms=engines.wav_duration_ms(data) if mime == "audio/wav" else None,
            rights_note=(rights_note or "Author confirmed they own this recording or have permission.")[:1000],
            status="imported", created_at=ctx.clock.iso(),
        )  # fmt: skip
        s.add(r)
        s.flush()
        activity.record(s, ctx, kind="recording_imported", project_id=project_id, ref_type="recording", ref_id=r.id,
                        summary=f"Imported recording “{r.title}”")  # fmt: skip
        return _rec_out(s, r)


def list_recordings(ctx: AppContext, project_id: str) -> list[RecordingOut]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        rows = s.scalars(
            select(Recording).where(Recording.project_id == project_id).order_by(Recording.created_at.desc())
        )
        return [_rec_out(s, r) for r in rows]


def get_recording(ctx: AppContext, project_id: str, recording_id: str) -> RecordingOut:
    with ctx.db.tx() as s:
        return _rec_out(s, _require_recording(s, project_id, recording_id))


def recording_file(ctx: AppContext, project_id: str, recording_id: str) -> tuple[Any, str]:
    with ctx.db.tx() as s:
        r = _require_recording(s, project_id, recording_id)
        orig = s.get(OriginalFile, r.original_file_id)
        if orig is None:
            raise NotFoundError("The recording's file is missing.")
        return safe_join(ctx.workspace.root, orig.storage_path), r.mime


def transcribe(ctx: AppContext, project_id: str, recording_id: str, data: TranscribeIn) -> RecordingOut:
    with ctx.db.tx() as s:
        require_active(s, project_id)
        r = _require_recording(s, project_id, recording_id)
        if s.scalars(
            select(TranscriptSegment.id).where(
                TranscriptSegment.recording_id == r.id, TranscriptSegment.source_id.is_not(None)
            )
        ).first():
            raise ConflictError(
                "Quotations from this transcript are already sources. Remove them before transcribing again."
            )
        _engine_ready(ctx, data.provider, engines.transcription_engines(_dev(ctx)))
        orig = s.get(OriginalFile, r.original_file_id)
        if orig is None:
            raise NotFoundError("The recording's file is missing.")
        path, name = safe_join(ctx.workspace.root, orig.storage_path), orig.original_name
    permit = key = None
    base_url = "https://api.openai.com/v1"
    if data.provider == "openai":
        provider, permit, key = _openai(ctx, data.openai_provider_id, project_id)
        base_url = provider.base_url or base_url
    audio = path.read_bytes()
    try:
        with cloud_activity("openai", data.provider != "openai"):
            segments = engines.transcribe(data.provider, audio, name, model=data.model, language=data.language, permit=permit,
                                          api_key=key, base_url=base_url, transport=ctx.http_transport)  # fmt: skip
    except engines.EngineError as exc:
        if exc.code in ("blocked", "unavailable", "auth", "too_large", "no_timestamps"):
            raise ConflictError(exc.message, extra={"reason": exc.code}) from exc
        with ctx.db.tx() as s:
            r = _require_recording(s, project_id, recording_id)
            r.status, r.error, r.provider, r.model = "failed", exc.message[:500], data.provider, data.model or None
            return _rec_out(s, r)
    with ctx.db.tx() as s:
        r = _require_recording(s, project_id, recording_id)
        for old in s.scalars(select(TranscriptSegment).where(TranscriptSegment.recording_id == r.id)):
            s.delete(old)
        s.flush()
        now = ctx.clock.iso()
        for i, g in enumerate(segments, start=1):
            if not g.text:
                continue
            label = g.speaker or "Speaker"
            s.add(TranscriptSegment(id=ctx.ids.new(), recording_id=r.id, ordinal=i, start_ms=max(0, g.start_ms),
                                    end_ms=max(g.start_ms, g.end_ms), speaker=f"Speaker {label}" if g.speaker else label,
                                    provider_speaker=g.speaker, text=g.text, created_at=now))  # fmt: skip
        r.status, r.error, r.provider, r.model, r.transcribed_at = (
            "transcribed",
            None,
            data.provider,
            data.model or None,
            now,
        )
        if r.duration_ms is None and segments:
            r.duration_ms = max(g.end_ms for g in segments)
        s.flush()
        activity.record(s, ctx, kind="recording_transcribed", project_id=project_id, ref_type="recording", ref_id=r.id,
                        summary=f"Transcribed “{r.title}” ({len(segments)} segment(s))")  # fmt: skip
        return _rec_out(s, r)


def set_speaker(ctx: AppContext, project_id: str, recording_id: str, segment_id: str, data: SpeakerIn) -> RecordingOut:
    with ctx.db.tx() as s:
        require_active(s, project_id)
        r = _require_recording(s, project_id, recording_id)
        g = s.get(TranscriptSegment, segment_id)
        if g is None or g.recording_id != r.id:
            raise NotFoundError("Segment not found.")
        if data.all_with_label:
            same = s.scalars(
                select(TranscriptSegment).where(
                    TranscriptSegment.recording_id == r.id, TranscriptSegment.speaker == g.speaker
                )
            )
            for x in same:
                x.speaker = data.speaker
        else:
            g.speaker = data.speaker
        s.flush()
        return _rec_out(s, r)


def _mmss(ms: int) -> str:
    return f"{ms // 60_000}:{ms // 1000 % 60:02d}"


def quote(ctx: AppContext, project_id: str, recording_id: str, data: QuoteIn) -> dict[str, Any]:
    """Turn chosen transcript segments into a knowledge source (exact text, speakers and timestamps)."""
    from pbs_core.services import knowledge

    with ctx.db.tx() as s:
        require_active(s, project_id)
        r = _require_recording(s, project_id, recording_id)
        if r.status != "transcribed":
            raise ConflictError("Transcribe the recording first.")
        segs = list(s.scalars(select(TranscriptSegment).where(TranscriptSegment.recording_id == r.id,
                                                               TranscriptSegment.id.in_(data.segment_ids))
                              .order_by(TranscriptSegment.ordinal)))  # fmt: skip
        if len(segs) != len(set(data.segment_ids)):
            raise ValidationFailedError("Some chosen segments are not part of this recording.")
        title = data.title or f"{r.title} ({_mmss(segs[0].start_ms)}–{_mmss(segs[-1].end_ms)})"
        lines = [
            f"# {title}", "",
            f"Quotation from the recording “{r.title}”, transcribed by {r.provider}{' (' + r.model + ')' if r.model else ''} "
            f"on {(r.transcribed_at or '')[:10]}. Speaker names were checked by the author. Check the wording against the "
            "audio before quoting it in print.", "",
        ]  # fmt: skip
        if r.provider == "mock":
            lines += ["WARNING: made with the built-in test engine. This is placeholder text, not real speech.", ""]
        for g in segs:
            lines += [f"> **{g.speaker}** [{_mmss(g.start_ms)}–{_mmss(g.end_ms)}]: {g.text}", ""]
        body = "\n".join(lines)
        fname = f"{(slugify(title) or 'quotation')[:60]}.md"
        ids = [g.id for g in segs]
    out = knowledge.import_source(ctx, None, fname, body.encode("utf-8"), project_id=project_id, allow_duplicate=True)
    if out.source is None:
        raise ConflictError("The quotation could not be saved as a source.")
    with ctx.db.tx() as s:
        for g in s.scalars(select(TranscriptSegment).where(TranscriptSegment.id.in_(ids))):
            g.source_id = out.source.id
        r = _require_recording(s, project_id, recording_id)
        return {"source": out.source.model_dump(), "recording": _rec_out(s, r).model_dump()}
