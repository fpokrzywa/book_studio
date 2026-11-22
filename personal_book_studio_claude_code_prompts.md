# Personal Book Studio — Claude Code Implementation Prompt Pack

**Purpose:** Build an original, private, local-first AI-assisted book-authoring and publishing desktop application that offers comparable *functions* to publicly advertised BookyAI features, without copying its code, design, brand, assets, or proprietary prompts.

**How to use:** Create an empty Git repository. Paste **Prompt 00** into a fresh Claude Code session, allow it to create the design documents, inspect the result, then paste Prompts **01–10** in order. Keep the same repository between sessions. Each prompt includes completion criteria. Do not move on until the phase is working. Save this file under `docs/BUILD_PROMPTS.md` in the repository if useful.

**Recommended implementation:** React + TypeScript + Vite frontend; Python 3.12+ FastAPI backend; SQLite/SQLAlchemy/Alembic local database and FTS5; local project asset directories; provider adapters for Ollama, OpenAI, Gemini, Anthropic, Groq; Pandoc as a conversion utility (with capability checks); WeasyPrint or an explicitly validated equivalent for print PDF; Tauri 2 packaging only after the web-hosted local version works. Prefer small and robust over overengineered. Verify each dependency's current compatibility before implementing.

**Release philosophy:** A successful export is not a guarantee of Amazon KDP approval; Amazon's final preview and review controls remain authoritative. No fake research figures. No ungrounded plagiarism-free claim. Never write silently over the user's manuscript.

## Prompt 00 — Principal Architect / persistent build charter

```text
Act as the Principal Software Architect, Lead Engineer, UX Designer, Publishing Systems Engineer, and QA Lead for a new PERSONAL application named "Personal Book Studio" (working name).

MISSION
Implement a clean-room, local-first AI-assisted book publishing studio with a complete workflow:
idea -> evidence-based research -> book brief -> outline -> chapter drafts -> human review and editing -> quality and continuity reviews -> covers and front/back matter -> multi-format export -> KDP preflight package.

Reference only the PUBLICLY DESCRIBED FUNCTIONS of BookyAI (https://special.bookyai.net/). Do NOT scrape or reproduce the site's source code, trade dress, promotional imagery, copy, logos, private prompts, or data. Create original UX, naming, component system, and architecture. Do not claim a clone of proprietary internals.

SCOPE
1. Personal, single-user application. No billing, subscriptions, multi-tenancy, user signup, SaaS infrastructure, or remote telemetry.
2. Supports macOS and Windows desktop eventually; start with a reliable local browser UI then package with Tauri 2.
3. Local project storage by default. No cloud sync. No third-party content transmission unless expressly requested or a cloud AI/research provider is chosen.
4. Optional Ollama local inference and optional cloud AI providers: OpenAI, Gemini, Anthropic, and Groq.
5. Supports nonfiction, fiction, courses/manuals, workbooks, memoirs, and serialized fiction.
6. Imports existing DOCX, Markdown, plain text, HTML, and text-based PDFs; clearly warn for scanned PDF OCR or lossy imports and preserve original uploads unchanged.
7. Preserve heading hierarchy, lists, tables, images/captions, code samples, mathematical expressions, footnotes/endnotes where feasible, bibliographies, link targets, and identifiers across save/import/export.
8. Version every AI and manual manuscript change. Support compare/restore and project backup/restore.
9. Maintain evidence/provenance for researched nonfiction and continuity for fiction; do not fabricate citations or sources.
10. Export Markdown, HTML, DOCX, EPUB, and a print-layout PDF. Optional MOBI/AZW3 via explicitly labeled external converter, not falsely represented as native or required by KDP.
11. Include preview, accessible UX, readable typography, progress, cancel/retry/resume, activity log, and approximate provider spending.
12. Support a book series/story bible, author style profile, market/keyword research, translation and narration as later features.

TECH STACK (default unless a proven blocker exists)
- React, TypeScript, Vite, accessible component library, responsive desktop-first UX.
- Python FastAPI local service, Pydantic contracts, SQLAlchemy + Alembic, SQLite with FTS5 and optional local embedding search. No Postgres/Redis required.
- Markdown plus a documented canonical structured block/asset model for books. Explicitly design the editor/import/export round-trip; use a richer editor only if content fidelity is provably retained.
- Local background job system with durable SQLite job records and idempotent resume after restart; do not rely on invisible in-memory jobs.
- Pandoc where useful for publishing formats; print PDF with deterministic CSS or equivalent, validated PDF inspections; EPUBCheck as optional validator.
- Tauri desktop shell after core features work; assess and document Python sidecar cross-platform bundling constraints.
- pytest, Vitest, React Testing Library, Playwright; linting, typing and migrations; test fixtures checked into the repo.

NON-NEGOTIABLE GOVERNANCE
- The user owns the work. Original uploads immutable. Destructive edits require explicit action. AI never silently overwrites approved content.
- Build an always-visible distinction between AI suggestion, human-approved text, and generated source claims.
- External sources are untrusted data; treat document content and web pages as prompt-injection surfaces.
- Source attribution must include document/URL, retrieved time, stable ID, page or location if available; unsupported claims must be flagged, not converted into citations.
- Local-only mode must fail closed; never fall back to cloud automatically.
- Credentials stored in operating system credential vault/keychain or equivalently secure mechanism; never exposed in logs, Git, exports, or database plaintext.
- Automated 'plagiarism score' must not pretend to prove global uniqueness. Explain limited overlap/duplicate detection transparently.
- AI-generated versus AI-assisted content tracking and user-facing KDP disclosure checklist.
- No automatic KDP account login or publishing. Produce a handoff package and validation instructions only.
- No fabricated citations, bestseller scores, keyword-search volumes, costs or provider capabilities.

START NOW — PLANNING ONLY, THEN STOP
A. Inspect the repository and OS/environment before choosing dependencies; do not assume anything is installed.
B. Create docs/PRD.md, docs/ARCHITECTURE.md (include data-flow diagram in Mermaid), docs/DATA_MODEL.md, docs/SECURITY.md, docs/ADR/0001-stack.md, docs/TEST_PLAN.md, docs/ROADMAP.md, docs/BUILD_STATE.md.
C. Document all core entities, state transitions, workspace boundaries, schema migration strategy, editing document schema, export pipeline, and risk register.
D. Produce an end-to-end acceptance scenario: create project -> ingest sources -> make outline -> generate chapter -> human edit -> restore version -> export EPUB/DOCX/PDF -> validate -> package.
E. Define acceptance gates for each phase and a concise phase-by-phase execution checklist.
F. Identify potentially unreliable third-party packages, OS-specific installation blockers, rights/licensing issues, and explicit fallbacks.
G. Write a precise implementation plan for Phase 01. Do not create placeholder feature screens falsely marked functional. Do not start Phase 01 in this response.

At the end, report created documents, decisions requiring validation, remaining risks, and what to paste next.
```

## Prompt 01 — Repo scaffold, shell, dashboard and vertical slice

```text
Continue the existing Personal Book Studio repository. First read docs/PRD.md, docs/ARCHITECTURE.md, docs/DATA_MODEL.md, docs/TEST_PLAN.md and docs/BUILD_STATE.md. Preserve agreed architecture unless a blocking issue requires a recorded ADR.

IMPLEMENT PHASE 01 END TO END
1. Set up frontend and backend, development commands, local-only API bound to loopback, CORS/origin restriction, configuration handling, basic error boundary, structured logging with secret redaction, and SQLite/Alembic migration.
2. Implement a responsive, accessible, ORIGINAL interface: left navigation (Library, New Book, Research, Manuscripts, Knowledge, Publishing, AI Settings, Activity, Help); dashboard cards for real projects and recent activity; proper empty and error states.
3. Implement functional project CRUD: new, open, rename, archive, duplicate, search/sort by title, project type, language, intended audience, target word count and publication format.
4. Provide a real persistent project library, not mock arrays or static cards. Seed data only in a separate demo script.
5. Add a fully working vertical slice: create project -> create a chapter -> enter content -> save -> restart app -> content still there -> export Markdown.
6. Add predictable local storage paths, sanitized filenames, safe path handling, migrations, and backup data structure. No external network calls in this phase.
7. Create README with precise Windows/macOS developer startup commands and troubleshooting. Add scripted setup where practical.
8. Write Playwright and backend tests for persistence, project isolation, and the full vertical slice.

DONE WHEN
- I can start the app with documented commands and use it in my browser.
- All basic navigation is functional, or a later-phase entry is clearly disabled and labeled 'not yet implemented'.
- All saved content survives restart and schema migration.
- `pytest`, frontend tests, lint, build and the vertical slice pass; report actual test results, not assumed results.
- Update docs/BUILD_STATE.md with work done, known limitations, and Phase 02 handoff. STOP.
```

## Prompt 02 — Book editor, rich content, import and chapter versioning

```text
Continue the SAME repo. Read docs/BUILD_STATE.md and relevant architectural contracts. Implement Phase 02; preserve existing features and migrations.

FEATURES
- Functional manuscript workspace: chapter tree, chapter/section drag-reorder, editable titles/slugs, word counts, target word count, status (planned/draft/in-review/approved), and quick navigation.
- Provide a pleasant editing experience with source/preview views or a rich editor chosen for LOSSLESS preservation of required structures. Support heading levels, paragraphs, lists, task lists, block quotes, hyperlinks, tables, code blocks, images with alt text/captions, simple math/LaTeX, footnotes and citations.
- Define and implement a canonical book document schema. The current chapter text, editor content and export must round-trip without silently destroying tables, citations, images, code or math. Document any limits and show warnings where content would be lost.
- Autosave with conflict protection; manual save; immutable chapter revisions; chronological versions; side-by-side text difference; restore as a NEW version; revision labels and notes.
- Book-level metadata and a canonical ordered chapter list. Reordering must not orphan assets, reference IDs, revisions or annotations.
- Import Markdown, .txt, .docx, .html and text-based PDF to new or existing project. Display detected chapters, preview proposed structure, check duplicates, warn on unsupported content. Preserve original files and import reports.
- Protect against unsafe links, HTML script injection, zip bombs and path traversal. Limit upload size and handle encrypted/unreadable docs.
- Add a project backup ZIP and restore flow with manifest, versioned schema, checksums and safe extraction. No silent overwrite of existing projects.

TESTS / ACCEPTANCE
- Import a multi-chapter fixture with a table, image/caption, code block, citation and math; edit; save; restart; round-trip; verify preservation.
- Restore a previous chapter revision, proving the newer revision remains in history.
- Reorder chapters and verify stable content/asset/citation references.
- Prove backup->restore produces equivalent manuscript and metadata.
- Run tests, repair failures, update BUILD_STATE and STOP.
```

## Prompt 03 — AI provider settings, routing, cost controls and durable jobs

```text
Continue SAME repo. Read docs/BUILD_STATE.md before changes. Implement Phase 03.

AI SETTINGS
- Provider adapters for Ollama, OpenAI, Google Gemini, Anthropic and Groq. Verify current official SDKs and endpoints; do not guess models or supported capabilities.
- Provider settings UI: add provider, key or local URL, test connection, discover or configure available model, task-specific default model, temperature/max output settings, provider health, explicit cloud/local privacy indication.
- Store keys securely using OS keychain/credential store where supported. In development use an explicit protected fallback with warning; NEVER store secrets in plaintext database, logs, Git, book exports or backup ZIP.
- Support task-aware routing: brainstorm, research, outline, draft, revise, summarize, translate. Explicit provider selection overrides defaults; no silent local-to-cloud fallback.
- Normalize chat generation, structured JSON output with validation, retry/backoff, timeouts, usage/cost recording, abort/cancel and errors. Provider-specific capabilities must be checked instead of assumed.
- Estimate tokens and projected charge BEFORE large jobs where feasible. Display actual usage returned by providers and clearly label estimated costs and unknown prices.

BACKGROUND JOBS
- Durable SQLite job queue with job ID, project/chapter ID, task, provider/model, status, progress, timestamps, retries, payload reference, error, provenance and output version. Processing must recover after restart, support cancellation, bounded concurrency and no duplicate final commits.
- Real status center with per-job logs, retry button, actionable failures and cost table. Do not invent progress percentages where unavailable; use stages.
- Keep requests scoped to specific projects. Enforce project-local content limits and user review before applying AI output.
- Provide mock/deterministic adapter for offline CI; integration smoke test for Ollama when available; live cloud checks opt-in only.

DONE WHEN
- I can choose a local model, ask it to draft a paragraph into a review pane, and accept it to create a chapter revision.
- Cancel/retry and application restart do not corrupt the chapter or double-apply results.
- Local-only mode demonstrably generates zero external AI calls.
- Automated tests pass; update BUILD_STATE and STOP.
```

## Prompt 04 — Knowledge base, citations, research grounding and author voice

```text
Continue SAME repo. Implement Phase 04, respecting documents and approvals.

KNOWLEDGE WORKSPACE
- Per-book or shared opt-in knowledge libraries with file import (MD/TXT/DOCX/HTML/text-PDF), deduplication, file hashes, indexing status, source titles, tags, user toggle enabled/disabled, remove/reindex.
- Chunk content with headings and page/paragraph anchors, record provenance, preserve raw originals. Build SQLite FTS5 search with highlighted passages; optionally add local embeddings/semantic search behind a capability flag. Hybrid ranking if enabled; transparent match reasons.
- Source-aware retrieval for chapter tasks: provide chunk IDs/page references to LLM; cite claims with links back to source passages; flag claims that cannot be located. Never fabricate titles, URLs, page numbers or DOI values.
- Separate evidence ledger from generated prose. Store claim text, supporting source IDs, review state, and stable citation keys; export citation metadata to bibliography later.
- An author voice workspace: import only my own writing or content I have rights to use; analyze sentence length, tone, formality, patterns and example fragments; store editable style guide per author/pen name. Show before/after examples and allow user corrections.
- An interview-to-book workspace: ask for stories/experiences, save exact user answers with provenance, and never invent a personal experience.
- Prompt injection isolation: knowledge/source text is untrusted material. It may supply facts but must not override application instructions or invoke tools. Safely escape external HTML.

ACCEPTANCE
- Imported sources are searchable, cited by exact passage and removable.
- Disabling a source prevents it from being used in new generations.
- A generated paragraph displays supporting sources or an explicit 'unverified' flag.
- Style rewrite is preview-only until accepted; the original chapter revision remains accessible.
- Tests cover provenance, injected malicious document text, deduplication, and backup/restore of citations. Update BUILD_STATE and STOP.
```

## Prompt 05 — Research, topic exploration, outline builder and planning

```text
Continue SAME repo. Implement Phase 05.

PROJECT PLANNING
- New Book wizard: fiction/nonfiction/manual/workbook/memoir, audience, purpose, main promise, tone, author profile, genre, target length, language, desired chapter count, sources, output format and approval preference.
- Research workspace: topic finder, query drafting, public-source search adapter(s) ONLY when configured, editable findings, source/date/URL capture, competitor title/metadata notes, KDP keyword brainstorming and evidence-based analysis.
- Do not claim sales rank, market size, demand, competition score, bestseller status or search volumes unless a real licensed source supplies them. Clearly separate heuristic observations from measured evidence.
- Book brief with target reader, core promise, exclusions, value proposition, teaching arc or plot arc, and explicit factual/creative assumptions.
- AI outline generation from brief and selected research, with stable section IDs, drag-reorder, merge/split, hierarchy, chapter-level goals, target words and estimated writing work. Proposal must be approved before any bulk manuscript generation.
- Nonfiction: source coverage and citation requirements per chapter; fiction: plot, character and continuity requirements.
- Preview estimated provider cost/time as estimates, with a configurable hard budget cap and number-of-chapters limit.
- Support 'outline first', 'one chapter', and 'entire book' modes. Every mode must honor manual edits and approved locks.

ACCEPTANCE
- From a new idea, build and approve a detailed outline using a deterministic test adapter without paid API access.
- Test that unsupported market metrics are never fabricated.
- Approved outline becomes durable chapter skeleton; a changed outline does not destroy existing prose or revision history.
- Fail-safe behavior on unavailable research provider is explicit. Update BUILD_STATE and STOP.
```

## Prompt 06 — Manuscript generation, editing, factual review and continuity

```text
Continue SAME repo. Implement Phase 06.

WRITING PIPELINE
- Draft by section, not a single giant prompt. For each section provide book brief, local outline, relevant prior chapter summaries, approved style guide, knowledge passages, plot/story bible where appropriate, targets and exclusions.
- Persist a structured generation plan and per-section jobs; retry failed sections without rewriting successful sections; allow pause/cancel/resume and user review gates.
- Avoid context blowups: chapter summaries, running continuity memory, retrieval and explicit token budget. Show task/provider/model provenance.
- Draft only into a proposed revision; accepted/locked manuscript content is never overwritten automatically.
- Editor actions: rewrite selection, expand/shorten, change tone, improve clarity, remove repetition, improve transitions, explain a passage, and generate exercise/quiz/glossary suggestions. Show diff + accept/reject.
- Quality reviews: grammar/style suggestions; repeated phrase detection; duplicated internal content; unsupported-claim flags; missing citations; mismatch with outline/reader promise; broken links; missing figure alt text; inconsistent terms and undefined acronyms.
- Fiction: chronology, character traits, location/relationship consistency, unresolved threads and timeline updates.
- Technical nonfiction: equations and code blocks must be preserved; validate code snippets with sandboxed tests only if explicitly authorized; mark unverified claims. Never describe AI review as proof of factual correctness.
- 'Originality' report must state scope: local duplicate checks and optional authorized similarity providers; absence of a match is NOT a guarantee of non-infringement or global uniqueness.

ACCEPTANCE
- Generate a short 3-chapter test book, stop, resume, and inspect draft job history.
- Demonstrate generated content does not supersede locked/approved material.
- Mark and review at least two unsupported facts in test data.
- Run an intentional repeated-paragraph check and verify a real finding.
- All tests, build and migration checks pass. Update BUILD_STATE and STOP.
```

## Prompt 07 — Book design, covers, interior layout and multi-format publishing

```text
Continue SAME repo. Implement Phase 07 with publishing-engine discipline.

BOOK ASSEMBLY
- Create configurable front/back matter: half-title/title page, copyright, dedication, epigraph, foreword/preface, introduction, acknowledgments, about author, bibliography/references, glossary, appendices, endnotes, index, call-to-action/discussion guide. Do not fabricate ISBN, copyright claims, endorsements or legal statements.
- Define reusable interior templates (technical manual, nonfiction, novel, workbook): trim size, fonts/licensing, headers/footers, chapter opening design, page numbers, TOC, mirrored margins, images, figure/table numbering and captions, code/math handling.
- Live HTML reading preview and accurate print-PDF preview. Provide warning if previews are not byte-identical to exports.
- Build exports: Markdown, HTML, editable DOCX, accessible/reflowable EPUB, and print-ready interior PDF. Use Pandoc/WeasyPrint or documented substitutes with deterministic templates. Treat MOBI/AZW3 as OPTIONAL external conversion if a supported tool is available; they are not primary KDP requirements.
- Validate round-trip fidelity for chapter order, headings, tables, hyperlinks, code, equations, images, captions, alt text and citation references; never silently omit unsupported types.
- Cover designer: use uploaded licensed artwork or configured image generation provider; render title, subtitle and author as editable typography layers (NOT image-model-generated lettering). Front ebook cover and print full-wrap cover (back + spine + front) using user-specified format, trim, paper/ink choices, FINAL page count and a verified current platform specification. Barcode safe area/bleed/spine constraints are required. Warn where actual printer measurements or a manual check are still needed.
- Preflight: PDF page dimensions and page count, bleed/margins (including binding gutter), font embedding, effective image resolution, language, missing assets, text overflow, cover dimensions, EPUB nav/metadata/link checks, DOCX validity, EPUBCheck if installed. Save full validation report with each export.
- Publishing metadata handoff: title/subtitle, author, description, seven potential keyword fields (editable), category suggestions (unverified until checked in KDP), age range, language, format, AI disclosure checklist.
- Generate a package directory with book exports, covers, metadata JSON/text, validation report, copyright/license notes, source list, and 'Manual KDP upload/preview steps'. Do not auto-publish.

REFERENCE RULES
- KDP trim/margins: https://kdp.amazon.com/en_US/help/topic/GVBQ3CMEQW3W2VL6
- Print manuscript: https://kdp.amazon.com/en_US/help/topic/G202145060
- Print cover: https://kdp.amazon.com/en_US/help/topic/G202187850
- Kindle Previewer: https://kdp.amazon.com/en_US/help/topic/G202131170
- Content/AI: https://kdp.amazon.com/en_US/help/topic/G200672390
These may change: fetch/check current official specifications during implementation, put source URL and checked-on date in docs, and expose validation-rule version in the UI. Never promise KDP approval.

ACCEPTANCE
- Export a fixture with 3 chapters, tables, images, math, code and citations to all five primary formats.
- Programmatically inspect PDF size, EPUB contents and DOCX paragraphs/styles.
- Show that a print cover automatically recalculates after final PDF page count changes.
- Validate EPUB via available tool or mark 'validation unavailable', never 'passed'.
- Produce and open the sample publish package and preflight report. Update BUILD_STATE and STOP.
```

## Prompt 08 — Book series, author personas, translations, narration (advanced)

```text
Continue SAME repo. Implement Phase 08 as ADVANCED FEATURES. Keep core publishing intact.

1. Series workspace: series/book relationships, shared story bible, characters (traits, aliases, relationships), location cards, plot threads, chronology and cross-book continuity. Store editable structured facts and provenance; distinguish author-approved canon from AI suggestions.
2. Series continuity review: compare new chapter text with canon; highlight contradictions with passage links; user resolves conflicts manually. Add an original character relationship visualization if practical; text editing must still work without it.
3. Author/pen-name profiles with editable voice rules; show which voice profile is active for each project.
4. Translation workflow: select an approved original revision, language and provider; persist localized editions as independent, linked revisions; preserve chapter IDs, named entities, figures, code/math, citations and structural links. Flag idiom/terminology inconsistencies for review. Don't overwrite the original.
5. Optional narration/audio: adapt chapters into speech-ready chunks; use configured local or cloud speech provider ONLY when user enables it; preserve chapter-to-audio alignment and progress; export audio with chapter metadata and transparent cost/licensing notes. Do not claim KDP audiobook/ACX compliance without specific validation.
6. Optional recorded interviews: import audio that the user owns, transcribe with an explicitly configured local/cloud service, allow speaker correction, retain timestamps and links, and let user select quotations as book sources. Never fabricate speech.

ACCEPTANCE
- Create two books in a shared fictional series, modify canon, detect an intentional contradiction, and preserve user resolution.
- Translate one chapter without editing source text; show language-specific chapter links.
- Narration and transcription features degrade gracefully if no provider is installed. No cloud calls in local-only mode.
- Tests pass, document optional dependencies, update BUILD_STATE and STOP.
```

## Prompt 09 — Security, performance, UX hardening and regression

```text
Continue SAME repo. Implement Phase 09 as a hardening release, not a feature-demo phase.

AUDIT
- Review every feature against docs/PRD.md and add a traceable implementation matrix: working, partial, absent, blocked, with links to code/tests.
- Execute integration tests on complete flow (new book through publication package) and import-existing-book workflow. Include offline/online provider paths, migrations, backup/restore and restart-with-running-job.
- Security: loopback binding, origin/CSRF protections as applicable, safe file paths and safe archive extraction, cross-project isolation, HTML/XSS sanitization, imported-source prompt injection, API secret redaction, cloud consent and local-only enforcement.
- Reliability: retries, per-task timeouts, job cancellation, bounded queue, disk errors, incomplete exports, partial imports, interrupted conversion tools, provider rate limits, concurrent edits, corrupted assets, and upgrade migrations.
- Accessibility: keyboard-only flows, readable contrast, labels, error announcements, screen-size handling, loading feedback, and visible data-sharing indicators.
- Performance: project with 100 chapters, hundreds of assets, thousands of source chunks; measure startup, search, editor responsiveness, export and disk footprint. Report actual numbers; no fabricated benchmark.
- Quality: hallucinated citations, unverified statistics, duplicated content, empty EPUB, image overflow, malformed PDF, zero-page print cover and invalid references should fail explicitly.
- Add in-app Help/How-To explaining local and cloud modes, provider configuration, imports, editing, versions, KDP export, disclosure and backups.

DELIVERABLES
- docs/FEATURE_MATRIX.md, docs/SECURITY_AUDIT.md, docs/KNOWN_LIMITATIONS.md, docs/RELEASE_CHECKLIST.md.
- Correct high-severity defects, rerun full tests, capture real test output, update BUILD_STATE, and STOP. No claims of perfection.
```

## Prompt 10 — macOS/Windows desktop packaging and installer

```text
Continue SAME repo. Implement Phase 10 ONLY after Phase 09 passes.

GOAL: Deliver a usable Personal Book Studio desktop application for macOS and Windows while keeping projects on local disk. Use Tauri 2 or another explicitly documented wrapper if needed to meet security, updater and packaging requirements.

1. Bundle or reliably bootstrap the required backend, frontend and supporting conversion dependencies. Identify code signing/notarization requirements, architectures (Apple Silicon/Intel, Windows x64/ARM if supported), bundled binary licenses and OS permissions.
2. Implement single-instance handling, app-data folder selection, secure credential storage, local service startup/shutdown, process health and port conflict resolution; no port exposed beyond loopback.
3. Provide first-run wizard (storage folder, sample project optional, Ollama detection, cloud AI optional, Pandoc/EPUBCheck capability checks, backup location).
4. Provide explicit dependency status and errors without a terminal. Where an external binary cannot legally or technically be bundled, show a guided manual installation step rather than claiming 'one-click'.
5. Build installation artifacts for OS targets available in the build environment; if macOS/Windows builds require separate runners, add CI workflows and explain the unsigned build limitations instead of pretending artifacts exist.
6. Add safe app updates and data/schema migrations with automatic backup before migration; rollback guidance. Never automatically upload books or telemetry.
7. Run smoke tests on actual target systems where available and label simulated/not-run checks as such.
8. Write docs/USER_GUIDE.md, docs/INSTALL.md, docs/RELEASE_NOTES.md, and exact scripts for development, build, test and recovery.

FINAL ACCEPTANCE
- A real user can create/import a book, draft/edit with local AI, inspect citations/history, preview, export and recover a project without a developer terminal during normal usage.
- No broken buttons masquerading as complete features. All unsupported features are visibly labeled.
- Provide binary paths only when files actually exist; otherwise provide reproducible CI/build steps.
- Report tests run, platform coverage, known limitations, and next suggested improvements. Update docs/BUILD_STATE.md.
```

## Useful follow-up prompt — Resume a new Claude Code session

```text
We are continuing the existing Personal Book Studio project, NOT starting a new one. Inspect the repository, read docs/BUILD_STATE.md, docs/ARCHITECTURE.md, docs/ROADMAP.md and the latest Git history. Explain completed phases, passing tests, current blockers, next pending phase and any schema/API contracts you must preserve. Then continue ONLY the pending phase I specify. Do not rebuild the project or replace functioning work. Update BUILD_STATE when finished.
```

## Useful follow-up prompt — Hard-stop test/review before advancing

```text
Act as an independent principal engineer and skeptical QA reviewer. Audit the phase just completed in the working repo. Inspect the actual code and run the stated tests. Verify the feature in a real end-to-end user flow, document remaining bugs with severity and repro steps, identify mock-only functionality, data-loss paths and insecure cloud fallbacks, and fix failures before recommending progression. Do not mark a feature complete because the interface displays it. Update docs/BUILD_STATE.md and docs/FEATURE_MATRIX.md with evidence.
```

## Suggested order and release checkpoints

- **Usable MVP:** Prompts 00–03. Projects, real editor, imports, history, AI adapters and background jobs.
- **Writing/research beta:** Prompts 04–06. Knowledge/citations, research, outlines, long-running drafting and review.
- **Publishing beta:** Prompt 07. Cross-format exports, covers and validation.
- **Feature-complete personal studio:** Prompt 08. Series, translation, narration, interviews.
- **Stable desktop release:** Prompts 09–10. Security, regression, installers and documentation.

**Critical sequencing:** Start with the export and document schema in Prompt 00, even though publishing occurs in Prompt 07. Otherwise the editor may strip technical content that the later export engine cannot recover. Do not spend the first week polishing a dashboard while document fidelity and storage remain unproven.

**Public functional reference:** https://special.bookyai.net/ (reviewed November 21, 2026). Specs and functionality should be independently implemented; vendor claims are not implementation proof.
