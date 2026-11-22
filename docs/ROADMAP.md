# Personal Book Studio — Roadmap, Phase Gates and Execution Checklist

Status: Draft v0.1 (Phase 00). Phases follow the user's prompt pack (`personal_book_studio_claude_code_prompts.md`), with one adjustment: **export-engine spikes move into Phase 02** so document fidelity is proven before AI and publishing work builds on it.

## Universal gate (applies to every phase)

A phase is **done** only when all of these hold:
- G0.1 All tests listed for the phase pass locally on Windows. Results are pasted into BUILD_STATE (counts, not adjectives).
- G0.2 `ruff`, `mypy` (strict modules), `eslint`, `tsc --noEmit`, the frontend build, import-linter, the license gate and the OpenAPI contract check are clean.
- G0.3 Migrations: fresh DB → head and previous-fixture DB → head both pass. A new fixture DB is added if the schema changed.
- G0.4 No UI control pretends to work. Unbuilt features show "Not yet available (Phase NN)".
- G0.5 Zero non-loopback network calls in the test suite (socket guard green).
- G0.6 BUILD_STATE.md is updated: done, known limitations, decisions taken, next-phase handoff. Any architecture change has an ADR.
- G0.7 Git: one or more commits on a phase branch. Nothing secret or personal committed (gitleaks clean).

## Phase overview

| Phase | Theme | Release checkpoint |
|---|---|---|
| 00 | Planning docs (this) | — |
| 01 | Scaffold, shell, project library, vertical slice, Markdown export | |
| 02 | Editor, BookMD/BDM fidelity, revisions/diff/restore, imports, backup/restore, **export-engine spikes** | |
| 03 | AI providers, egress gate, keyring, routing, cost, durable jobs, proposals | **Usable MVP** |
| 04 | Knowledge base, citations, evidence ledger, voice, interviews | |
| 05 | Research, brief, outline builder, planning, budgets | |
| 06 | Sectioned generation, editor AI actions, quality and continuity reviews, originality report | **Writing/research beta** |
| 07 | Book design, front/back matter, all exports, covers, preflight, KDP package | **Publishing beta** |
| 08 | Series bible, pen names, translation, narration, transcription | **Feature-complete** |
| 09 | Security/perf/a11y hardening, feature matrix, regression | |
| 10 | Tauri 2 desktop packaging, first-run wizard, installers | **Stable desktop** |

## Phase gates (acceptance criteria)

### Phase 01: Scaffold and vertical slice
- G1.1 `scripts/dev.ps1` (and `dev.sh`) starts Core (127.0.0.1:8765) + UI (localhost:5173). README has exact Windows and macOS commands.
- G1.2 Guard middleware: Host allowlist, Origin check, session token. Tests T-S1–T-S5 pass.
- G1.3 Alembic baseline migration creates the Phase 01 tables with immutability triggers and composite FKs. T-P7 passes.
- G1.4 Project CRUD (create, open, rename, archive/unarchive, duplicate), search by title and sort by the listed fields, all backed by the DB. Tests T-P1, T-P4, T-P5 pass.
- G1.5 Vertical slice in Playwright: create project → create chapter → type content → save → **restart Core** → content present → export Markdown → file content matches. Golden steps 1–3 and the MD part of 11 pass.
- G1.6 Navigation: Library and Manuscripts (chapter list + editor) are functional. New Book is functional as the basic create-project form. Research, Knowledge, Publishing, AI Settings: labeled "Not yet available". Activity: functional list. Help: functional static help + a **local capability report** (detected Pandoc/Java/WeasyPrint/Ollama binaries by PATH lookup only, no network).
- G1.7 Privacy badge visible ("Local-only"), with no way yet to enable cloud.
- G1.8 Accessibility: axe has no serious/critical violations on all Phase 01 screens. The keyboard-only vertical slice passes.

### Phase 02: Editor, fidelity, history, import, backup, spikes
- G2.1 BookMD parser + BDM + HTML and Markdown writers. T-D1–T-D6 pass on `kitchen-sink.md`.
- G2.2 ADR-0002 (editor choice) recorded with bake-off evidence. The chosen editor passes the fidelity suite.
- G2.3 Chapter tree with keyboard-accessible reorder, status, lock, word counts, targets.
- G2.4 Autosave + conflict 409 + revision list + diff + restore-as-new + labels/notes. Golden steps 8–10 pass.
- G2.5 Imports (MD, TXT, HTML, DOCX via Pandoc|mammoth, text PDF) with preview, import report, immutable originals, scanned/encrypted warnings. Malicious fixtures rejected safely.
- G2.6 Backup ZIP (manifest/1, checksums) → restore as a new project yields a structurally equivalent project. Golden step 14 passes.
- G2.7 **Spikes (throwaway code under `spikes/`, results in ADR-0003):** WeasyPrint on this Windows machine, `kitchen-sink.md` → PDF with fonts embedded; ziamath math → SVG; Pandoc DOCX from the BDM→Pandoc AST writer. Each records pass/fail and the chosen fallback.

### Phase 03: AI and jobs (MVP)
- G3.1 Adapters: mock, Ollama, OpenAI, Anthropic, Gemini, Groq. Each has recorded-fixture contract tests. Live tests are opt-in.
- G3.2 Keyring storage. Canary-key artifact scan passes. Env-var fallback shows a warning.
- G3.3 Egress gate. T-J6 (zero egress, no fallback) passes.
- G3.4 Durable jobs. T-J1–T-J5 pass (restart, cancel, retry, stale, lock).
- G3.5 Review pane: draft a paragraph with a local (or mock) model → diff → accept → revision with `origin=ai_generated`. Golden steps 6–7 pass with the mock provider.
- G3.6 Status center with per-job logs, retry, and a cost table showing "estimate" and "unknown" labels.

### Phase 04: Knowledge and evidence
- G4.1 Libraries (project + shared opt-in), dedupe, enable/disable, reindex, FTS5 with highlights.
- G4.2 Grounded generation passes chunk IDs. Claims link to passages or are flagged Unverified. A disabled source is never used.
- G4.3 Evidence ledger CRUD. Citation keys resolve only to ledger/citation rows.
- G4.4 Injection fixture suite passes. Voice profile with a rights attestation. Rewrite is preview-only.
- G4.5 Backup/restore preserves sources, chunks, claims and citations.

### Phase 05: Planning
- G5.1 New Book wizard, brief, research workspace (adapters only when configured; heuristic vs measured are visibly separated).
- G5.2 Outline proposal → edit → approve → chapter skeleton. Changing the outline never destroys prose or history.
- G5.3 Budget and chapter caps enforced before enqueueing. Estimates labeled.
- G5.4 Test: no market metric fields are populated without a licensed source.

### Phase 06: Writing pipeline and reviews
- G6.1 Sectioned generation plan + per-section steps. Stop/resume on a 3-chapter test book. Successful sections are not regenerated.
- G6.2 Locked/approved content untouched (test).
- G6.3 Selection actions with diff accept/reject.
- G6.4 Reviews: ≥2 planted unsupported facts flagged. A planted repeated paragraph found. Fiction continuity check on a fixture.
- G6.5 Originality report shows its scope statement.

### Phase 07: Publishing
- G7.1 KDP specs fetched from the official pages, stored in `kdp_spec` with `source_url` + `checked_on`, rule version shown in the UI.
- G7.2 Five primary exports from the 3-chapter fixture. Programmatic inspections pass (TEST_PLAN golden step 12).
- G7.3 Covers: ebook front + print wrap. The spine recalculates on a page-count change (test). Text is rendered as editable layers.
- G7.4 Preflight report with pass/warn/fail/unavailable. EPUBCheck "unavailable" when Java is missing.
- G7.5 KDP package with the manual steps document. Disclosure checklist derived from revision origins. No auto-publish anywhere.

### Phase 08: Advanced
- G8.1 Two-book series. A canon edit and a planted contradiction are detected. The user's resolution persists.
- G8.2 A chapter translation becomes a linked edition. Source revisions are untouched.
- G8.3 Narration and transcription degrade gracefully without providers, and make zero cloud calls in local-only mode.

### Phase 09: Hardening
- G9.1 `FEATURE_MATRIX.md` (working/partial/absent/blocked, linked to code and tests), `SECURITY_AUDIT.md`, `KNOWN_LIMITATIONS.md`, `RELEASE_CHECKLIST.md`.
- G9.2 Performance measured on the 100-chapter fixture. Real numbers recorded.
- G9.3 All high-severity defects fixed. Full regression green, with the output captured.

### Phase 10: Desktop
- G10.1 Tauri 2 app on Windows (x64) launches the sidecar, single instance, loopback only, token handoff.
- G10.2 First-run wizard + dependency status without a terminal.
- G10.3 Installer artifacts only for targets actually built. CI workflows for the others, with unsigned limitations documented.
- G10.4 Pre-migration backup and rollback guide. No telemetry or auto-upload.

## Execution checklist (per phase, in order)

```
[ ] 1. Read BUILD_STATE.md + docs touched by the phase; re-run the full test suite (baseline must be green)
[ ] 2. Create branch  phase/NN-<slug>
[ ] 3. Write/extend failing tests for the phase gates first (TDD where practical)
[ ] 4. Schema changes → Alembic migration + fixture DB + migration test
[ ] 5. Backend services + API (Pydantic contracts) → regenerate TS client
[ ] 6. Frontend screens (real data only; disabled+labeled for later phases)
[ ] 7. Security checks for the phase (SECURITY.md §8)
[ ] 8. Extend E2E-GOLDEN-01; flip xfail → pass for this phase's steps
[ ] 9. Lint, type, build, license gate, gitleaks, socket guard
[ ] 10. Manual smoke in a browser (Windows); note anything not verifiable
[ ] 11. Update BUILD_STATE.md (evidence pasted), ADRs if any decisions changed
[ ] 12. Commit; STOP and hand back to the user
```

## Out of scope until explicitly requested

Cloud sync, multi-user, mobile apps, a plugin marketplace, automatic KDP actions, licensed market-data integration (needs a user-provided source), OCR.
