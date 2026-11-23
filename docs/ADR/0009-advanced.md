# ADR-0009: Advanced features: series canon and continuity, pen names, translated editions, narration, recorded interviews

Status: Proposed (Phase 08, 2026-11-23). Needs the author's sign-off (decisions P8-1 to P8-12 in BUILD_STATE).

## Context
Phase 08 adds optional, advanced features on top of the core manuscript, writing and publishing flow. None of them may weaken that flow. The constraints are:
- **Author approval.** Series canon is the author's. AI or imported suggestions stay separate until the author approves them, and every fact keeps its provenance.
- **Continuity findings.** They point at passages; they never change text. The author resolves each one, and the decision survives re-runs.
- **Translations.** Never overwrite the original. Keep chapter identity, names, figures, code, math, citations and links. Flag idioms and terminology for review.
- **Narration and transcription.** Both are opt-in, use local or cloud engines only when configured, and fail closed in local-only mode with a clear reason. They must work (degrade) with no engine installed.
- **Honesty.** Never fabricate speech, costs, licences or store compliance. KDP audiobook/ACX compliance is not claimed.

## Decisions

### 1. Series canon is a separate store with explicit status and provenance
Tables `series`, `series_book`, `canon_entity`, `canon_fact` and `canon_relationship` (migration `0009_advanced`).
- **Status.** Every entity, fact and relationship has a `status` (`canon`, `suggested` or `rejected`) and an `origin` (`author`, `ai_suggested` or `book_note`), plus `provenance_json`: who added it, from which chapter or revision or continuity finding, and the excerpt.
- **What counts.** Only `canon`, not-superseded rows are used for checks and prompts. Suggestions never leak into prompts or reviews.
- **History.** Changing a fact's value creates a new row and points the old one at it (`superseded_by`), so earlier canon stays visible ("Earlier values").
- **Book notes.** A book's Phase 06 continuity notes can be imported. Confirmed notes become canon; the rest become suggestions. The book itself is not changed.
- **Prompts.** `writing/memory.fact_items` now includes the series canon for every book in the series, so drafting prompts see it.

### 2. Continuity review is rule-based, deterministic and passage-linked
`pbs_core/series/continuity.py` compares the current text of each chapter with approved canon:
- colour traits (eye or hair colour) in sentences naming the character, by name or alias;
- ages ("N years old");
- a character canon says is dead who speaks or acts (flagged as "fine in a flashback");
- family relationships written as "B's <kin> A" against the canon kin word.

The chronology view orders event facts by story time and flags events out of book order.
- **Findings.** Each finding has offsets into the chapter source and a link `/projects/{pid}/chapters/{cid}?select=start-end`; the editor opens with that passage selected.
- **Fingerprints.** A finding's fingerprint is rule + canon reference + chapter + normalised excerpt. Re-running updates positions but keeps the author's decision. Findings no longer in the text are marked `present = false`, and their decisions are kept.
- **Resolutions.** These are manual: "canon is right" (`keep_canon`), "the text is right, update canon" (creates a new fact or relationship label with provenance pointing at the finding), "intended" (with a note), or "reopen".
- **Why rules, not a model.** The result is reproducible, costs nothing, runs offline and never invents a contradiction. The rules are narrow on purpose (limitation 1).

### 3. Pen names and voice rules extend the existing author profile
`author_profile` gains `pen_name` and `voice_rules_json` (a list of `do` or `avoid` rules). The book's brief already names the voice profile in use (`book_brief.author_profile_id`). The book page shows the active profile, pen name and rule count, and lets the author change it. The rules are included in every writing and rewrite prompt that uses the profile.

### 4. A translated edition is an independent, linked book
- **The edition.** `translation_edition` links a source book to a new target project, with its own language and title. The target gets a mirrored chapter tree: same slugs, positions and outline node IDs (chapter identity preserved). `chapter_translation` maps each target chapter to its source chapter and records the source revision translated.
- **Approval rule.** Only an approved original is translated: the current head of a chapter marked Approved, or any revision labelled "Approved" in history. The source revision is only ever read.
- **Protection.** `translation/protect.py` extends the writing protector. It masks code, math, citations, footnote markers, link and image targets, attribute blocks and raw HTML as `⟦KEEP-n⟧`. A reply that loses, alters or repeats a placeholder is rejected as `invalid_output` (and retried) and is never offered.
- **Checks.** After unmasking, `translation.protect.check` flags dropped names (from series canon and confirmed notes), term-list violations, and changed heading, list, table-row or paragraph counts. The model's own notes on idioms and terminology are added. Each item can be marked checked.
- **Result.** The output is a proposal on the edition's chapter, accepted or rejected like any suggestion. Editions of editions, a duplicate language, or the source language are refused.
- **Links.** Chapter links are shown both ways in the editor ("Translated from …", and "fr: …") and flag a translation as stale when the original has moved on.

### 5. Narration: a script first, audio only on request
`media/narration.py` turns the chapter's document model into speech-ready parts.
- **What is read.** Prose is read as written. Citations and footnote markers are not read. Code, equations and tables are announced ("A code listing appears here in the book") and noted for the author. Figures read their alt text.
- **Parts.** Parts break at sentence ends within a configurable limit (200–4000 characters; OpenAI's 4096-character limit is enforced). Each part keeps the block IDs it reads, for chapter-to-audio alignment.
- **Settings.** Narration settings are per book (`narration:{project_id}`) and are **off by default**. The script can always be prepared and read, with no engine needed.
- **Audio.** It is made synchronously for the next N parts, only when narration is on and an engine is chosen.
- **Engines:**

  | Engine | Where it runs | Notes |
  |---|---|---|
  | Built-in test engine | this computer | dev and test only; produces labelled silence |
  | eSpeak NG | this computer | `espeak-ng` on PATH |
  | Piper | this computer | `piper` on PATH plus `PBS_PIPER_MODEL` |
  | OpenAI speech | cloud | through the egress gate |

- **Progress.** Progress is per chapter (`narration_chunk` rows: pending, done or failed, with duration and cost). A new revision gets a new script; old audio is flagged, not reused.
- **Export.** A ZIP with one WAV per fully narrated chapter, `chapters.json` (per-part start times and block IDs), a `.cue` sheet and `NOTES.txt`. The notes give the engines, cost, the AI-voice disclosure, licensing notes, and "Not checked against ACX/Audible or KDP audiobook requirements".
- **Cost.** Cost is computed only from a price the author enters (per million characters). Otherwise it is "unknown". Local engines cost 0.

### 6. Recorded interviews: the author's audio, an explicit engine, immutable transcripts
- **Import.** Import requires the author to confirm they own the recording or have the speakers' permission. The file must be real audio (magic bytes: WAV, MP3, MP4/M4A, FLAC, OGG, WebM). It is stored byte for byte as a read-only original.
- **Engines:**

  | Engine | Where it runs | Notes |
  |---|---|---|
  | Built-in test engine | this computer | dev and test only; text labelled "not real speech" |
  | Whisper CLI | this computer | `whisper` on PATH; ffmpeg for compressed audio |
  | OpenAI transcription | cloud | `whisper-1` for timestamps; `gpt-4o-transcribe-diarize` for timestamps and speakers |

  Models without timestamps are refused.
- **Transcripts.** Segment text and timestamps are immutable in the database (trigger `transcript_segment_immutable`). Only speaker names can be corrected, one segment or every segment with the same label.
- **Quotations.** Chosen segments become a knowledge source (Markdown) with the exact text, speakers and `[m:ss–m:ss]` timestamps, and a note naming the engine. Segments remember the source they went into, and re-transcribing is refused while quotations exist. PBS never generates or edits speech text.

### 7. Cloud access for audio uses the same gate as text
OpenAI audio calls go through `providers.egress.gated_client` with a permit from `registry.permit_for`. That requires cloud mode, the book's consent for that provider, and a key from the OS credential store. The service checks the permit **before** building any request and answers 409 with the reason ("Local-only mode is on…", "This project has not been allowed…"). Nothing is sent. The media status endpoint marks cloud engines unavailable in local-only mode.

## OpenAI audio API facts used (read 2026-11-23)
- **Speech:** https://developers.openai.com/api/reference/resources/audio/subresources/speech/methods/create and https://developers.openai.com/api/docs/guides/text-to-speech.
  - `POST /v1/audio/speech` with JSON `{model, input (max 4096 characters), voice, response_format}`; PBS asks for `wav`. The response is raw audio.
  - Models listed include `tts-1`, `tts-1-hd` and `gpt-4o-mini-tts`; voices include `marin` and `cedar`.
  - OpenAI's usage policies require telling listeners the voice is AI-generated; PBS puts this in `NOTES.txt` and on the page.
  - Several listed models carry deprecation notices (a shutdown announced for 2027-01-06). The model is a free-text setting, so the author can move to a successor without a code change.
- **Transcription:** https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create and https://developers.openai.com/api/docs/guides/speech-to-text.
  - `POST /v1/audio/transcriptions`, multipart `{file, model, response_format, …}`, files up to 25 MB.
  - Segment timestamps: `whisper-1` with `response_format=verbose_json` (segments with `start`, `end` and `text`).
  - Speaker labels: `gpt-4o-transcribe-diarize` with `response_format=diarized_json` and `chunking_strategy=auto` (segments with `speaker`).
  - Shutdowns are announced for 2027-02-26 for these models.
- **Prices** are not built in (they change). The author enters the current price, or the cost is "unknown".

## Consequences
- Advanced features are additive. The core publishing flow and its tests are unchanged (all earlier tests pass).
- **Real audio engines are not installed on the development machine.** eSpeak NG, Piper and Whisper were exercised only through their "not installed" paths, and OpenAI audio only against a recorded wire format (mock transport). Real output quality is unverified.
- **The continuity rules are English-centric and narrow.** They complement, not replace, a human read.
