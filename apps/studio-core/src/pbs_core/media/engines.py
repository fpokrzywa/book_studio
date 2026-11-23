"""Speech and transcription engines. Every one is optional; nothing runs unless the author enables it.

Local engines run only if their program is installed (found on PATH):
* ``espeak-ng`` (or ``espeak``) and ``piper`` (with ``PBS_PIPER_MODEL`` pointing at a voice model) for speech;
* ``whisper`` (the openai-whisper command line) for transcription.
The cloud engine is OpenAI's audio API, called only through the egress gate, so local-only mode
blocks it before anything is sent. The built-in test engines (dev and test only) produce labelled
silence and labelled placeholder text: they never pretend to be speech.

OpenAI facts used (read 2026-11-23 from developers.openai.com API reference and guides):
* speech: POST /v1/audio/speech, JSON {model, input (max 4096 characters), voice, response_format "wav"};
  models tts-1, tts-1-hd, gpt-4o-mini-tts (deprecated, shut-down announced for 2027-01-06); voices include
  marin and cedar; the response is raw audio. OpenAI's usage policies require telling listeners the voice
  is AI-generated.
* transcription: POST /v1/audio/transcriptions, multipart {file, model, response_format}; segment
  timestamps need whisper-1 with verbose_json (segments: start, end, text); speaker labels need
  gpt-4o-transcribe-diarize with diarized_json and chunking_strategy=auto (segments: start, end, text,
  speaker); files up to 25 MB; whisper-1 and the diarize model are announced to shut down 2027-02-26.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx2

from pbs_core.providers.egress import EgressBlockedError, EgressPermit, gated_client

OPENAI_SPEECH_MAX_CHARS = 4096
OPENAI_UPLOAD_MAX = 25 * 1024 * 1024
SOURCES = {
    "openai_speech": "https://developers.openai.com/api/reference/resources/audio/subresources/speech/methods/create",
    "openai_tts_guide": "https://developers.openai.com/api/docs/guides/text-to-speech",
    "openai_transcription": "https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create",
    "openai_stt_guide": "https://developers.openai.com/api/docs/guides/speech-to-text",
}
CHECKED_ON = "2026-11-23"
AI_VOICE_NOTICE = (
    "This narration uses a synthetic (AI-generated) voice. Tell listeners so; OpenAI's usage policies require it when "
    "its voices are used, and most stores ask for it."
)
NOT_ACX = (
    "Not checked against ACX/Audible or KDP audiobook requirements (loudness, peak level, noise floor, room tone, file "
    "format and per-chapter rules). Validate with the store's own specification before submitting."
)


class EngineError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class Segment:
    start_ms: int
    end_ms: int
    text: str
    speaker: str | None = None


def _which(*names: str) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def speech_engines(dev: bool) -> list[dict[str, Any]]:
    espeak = _which("espeak-ng", "espeak")
    piper = _which("piper")
    piper_model = os.environ.get("PBS_PIPER_MODEL", "")
    out = []
    if dev:
        out.append(
            {
                "kind": "mock",
                "label": "Built-in test engine (silence, not speech)",
                "local": True,
                "available": True,
                "reason": "",
            }
        )
    out.append({"kind": "espeak", "label": "eSpeak NG (on this computer)", "local": True, "available": bool(espeak),
                "reason": "" if espeak else "Not installed: install espeak-ng and make sure it is on PATH."})  # fmt: skip
    ok_piper = bool(piper and piper_model and Path(piper_model).is_file())
    out.append({"kind": "piper", "label": "Piper (on this computer)", "local": True, "available": ok_piper,
                "reason": "" if ok_piper else "Not installed: install piper and set PBS_PIPER_MODEL to a voice model file."})  # fmt: skip
    out.append({"kind": "openai", "label": "OpenAI speech (cloud)", "local": False, "available": True,
                "reason": "Needs an OpenAI provider with a key, cloud mode allowed and this book's permission."})  # fmt: skip
    return out


def transcription_engines(dev: bool) -> list[dict[str, Any]]:
    whisper = _which("whisper")
    out = []
    if dev:
        out.append(
            {
                "kind": "mock",
                "label": "Built-in test engine (placeholder text, not real speech)",
                "local": True,
                "available": True,
                "reason": "",
            }
        )
    out.append({"kind": "whisper_cli", "label": "Whisper (on this computer)", "local": True, "available": bool(whisper),
                "reason": "" if whisper else "Not installed: install openai-whisper (needs ffmpeg) so `whisper` is on PATH."})  # fmt: skip
    out.append({"kind": "openai", "label": "OpenAI transcription (cloud)", "local": False, "available": True,
                "reason": "Needs an OpenAI provider with a key, cloud mode allowed and this book's permission."})  # fmt: skip
    return out


def wav_duration_ms(data: bytes) -> int | None:
    try:
        with wave.open(io.BytesIO(data)) as w:
            return int(w.getnframes() * 1000 / w.getframerate())
    except (wave.Error, EOFError, ZeroDivisionError):
        return None


def _silence_wav(ms: int, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(rate * ms / 1000))
    return buf.getvalue()


def speak(kind: str, text: str, *, voice: str = "", model: str = "", permit: EgressPermit | None = None,
          api_key: str | None = None, base_url: str = "https://api.openai.com/v1", transport: Any = None) -> bytes:  # fmt: skip
    """Synthesize one chunk. Returns WAV bytes."""
    if not text.strip():
        raise EngineError("empty", "Nothing to read.")
    if kind == "mock":
        return _silence_wav(min(60_000, 40 * len(text)))
    if kind in ("espeak", "piper"):
        exe = _which("espeak-ng", "espeak") if kind == "espeak" else _which("piper")
        if not exe:
            raise EngineError("unavailable", f"{kind} is not installed on this computer.")
        work = Path(tempfile.mkdtemp(prefix="pbs-tts-"))
        try:
            out = work / "out.wav"
            if kind == "espeak":
                cmd = [exe, "-v", voice or "en", "-w", str(out), "--stdin"]
            else:
                model_path = os.environ.get("PBS_PIPER_MODEL", "")
                if not model_path or not Path(model_path).is_file():
                    raise EngineError("unavailable", "Set PBS_PIPER_MODEL to a Piper voice model file.")
                cmd = [exe, "--model", model_path, "--output_file", str(out)]
            proc = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=300, check=False)  # noqa: S603
            if proc.returncode != 0 or not out.is_file():
                raise EngineError("failed", f"{kind} failed: {(proc.stderr or '').strip()[:300]}")
            return out.read_bytes()
        finally:
            shutil.rmtree(work, ignore_errors=True)
    if kind == "openai":
        if permit is None:
            raise EngineError("blocked", "No permission to use the cloud. Nothing was sent.")
        if len(text) > OPENAI_SPEECH_MAX_CHARS:
            raise EngineError(
                "too_long", f"OpenAI speech takes at most {OPENAI_SPEECH_MAX_CHARS} characters per request."
            )
        if not api_key:
            raise EngineError("auth", "The OpenAI provider has no API key.")
        try:
            with gated_client(permit, transport=transport, timeout=300.0) as http:
                r = http.post(
                    base_url.rstrip("/") + "/audio/speech",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model or "gpt-4o-mini-tts",
                        "input": text,
                        "voice": voice or "marin",
                        "response_format": "wav",
                    },
                )
        except EgressBlockedError as exc:
            raise EngineError("blocked", str(exc)) from exc
        except httpx2.HTTPError as exc:
            if isinstance(exc.__cause__, EgressBlockedError):
                raise EngineError("blocked", str(exc.__cause__)) from exc
            raise EngineError("failed", "OpenAI could not be reached.") from exc
        if r.status_code != 200:
            raise EngineError("failed", f"OpenAI answered with an error ({r.status_code}).")
        return r.content
    raise EngineError("unknown", f"Unknown speech engine {kind!r}.")


def transcribe(kind: str, data: bytes, filename: str, *, model: str = "", language: str = "", permit: EgressPermit | None = None,
               api_key: str | None = None, base_url: str = "https://api.openai.com/v1", transport: Any = None) -> list[Segment]:  # fmt: skip
    if kind == "mock":
        h = hashlib.sha256(data).hexdigest()[:8]
        dur = wav_duration_ms(data) or 9000
        step = max(1, dur // 3)
        return [
            Segment(i * step, min(dur, (i + 1) * step),
                    f"[Test transcription, not real speech] Segment {i + 1} of recording {h}.", "A" if i % 2 == 0 else "B")
            for i in range(3)
        ]  # fmt: skip
    if kind == "whisper_cli":
        exe = _which("whisper")
        if not exe:
            raise EngineError("unavailable", "Whisper is not installed on this computer.")
        work = Path(tempfile.mkdtemp(prefix="pbs-stt-"))
        try:
            f = work / ("audio" + (Path(filename).suffix.lower()[:8] or ".wav"))
            f.write_bytes(data)
            cmd = [exe, str(f), "--model", model or "base", "--output_format", "json", "--output_dir", str(work)]
            if language:
                cmd += ["--language", language]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, check=False)  # noqa: S603
            out = work / (f.stem + ".json")
            if proc.returncode != 0 or not out.is_file():
                raise EngineError("failed", f"Whisper failed: {(proc.stderr or '').strip()[-300:]}")
            js = json.loads(out.read_text(encoding="utf-8"))
            return [
                Segment(int(float(x["start"]) * 1000), int(float(x["end"]) * 1000), str(x["text"]).strip())
                for x in js.get("segments", [])
            ]
        finally:
            shutil.rmtree(work, ignore_errors=True)
    if kind == "openai":
        if permit is None:
            raise EngineError("blocked", "No permission to use the cloud. Nothing was sent.")
        if len(data) > OPENAI_UPLOAD_MAX:
            raise EngineError(
                "too_large", "OpenAI transcription takes files up to 25 MB. Split or compress the recording."
            )
        if not api_key:
            raise EngineError("auth", "The OpenAI provider has no API key.")
        model = model or "whisper-1"
        if model == "gpt-4o-transcribe-diarize":
            form: dict[str, Any] = {"model": model, "response_format": "diarized_json", "chunking_strategy": "auto"}
        elif model == "whisper-1":
            form = {"model": model, "response_format": "verbose_json", "timestamp_granularities[]": "segment"}
        else:
            raise EngineError(
                "no_timestamps", f"{model} returns no timestamps. Choose whisper-1 or gpt-4o-transcribe-diarize."
            )
        if language:
            form["language"] = language
        try:
            with gated_client(permit, transport=transport, timeout=900.0) as http:
                r = http.post(base_url.rstrip("/") + "/audio/transcriptions", headers={"Authorization": f"Bearer {api_key}"},
                              data=form, files={"file": (filename, data)})  # fmt: skip
        except EgressBlockedError as exc:
            raise EngineError("blocked", str(exc)) from exc
        except httpx2.HTTPError as exc:
            if isinstance(exc.__cause__, EgressBlockedError):
                raise EngineError("blocked", str(exc.__cause__)) from exc
            raise EngineError("failed", "OpenAI could not be reached.") from exc
        if r.status_code != 200:
            raise EngineError("failed", f"OpenAI answered with an error ({r.status_code}).")
        body = r.json()
        return [
            Segment(
                int(float(x["start"]) * 1000), int(float(x["end"]) * 1000), str(x["text"]).strip(), x.get("speaker")
            )
            for x in body.get("segments", [])
        ]
    raise EngineError("unknown", f"Unknown transcription engine {kind!r}.")
