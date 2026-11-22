# Personal Book Studio — Product Requirements Document

Status: Draft v0.1 (Phase 00, planning). Owner: the user (sole author and operator).
Last updated: 2026-11-22.

## 1. Product statement

Personal Book Studio (PBS, working name) is a **private, single-user, local-first desktop studio** for taking a book from idea to a validated, upload-ready publishing package. AI helps with research, planning, drafting and review, but the author decides: every AI output is a proposal until the author accepts it, and every change is versioned.

The workflow:

```
idea → evidence-based research → book brief → outline → chapter drafts
     → human review & editing → quality / continuity reviews
     → covers + front/back matter → multi-format export → KDP preflight package
```

### 1.1 Clean-room statement

PBS offers functions comparable to those **publicly described** for BookyAI (https://special.bookyai.net/, reviewed by the user on 2026-11-21). We have not scraped, copied or reproduced its source code, prompts, data, copy, imagery, logo, trade dress, naming or layout, and we will not. All UX, naming, component design, architecture and prompts are original. PBS is not a clone of anything proprietary and must never be described as one.

### 1.2 Non-goals

- Billing, subscriptions, accounts, sign-up, multi-tenancy, teams, SaaS hosting.
- Cloud sync and remote telemetry (no analytics, crash reporting or update pings unless the user turns them on later).
- Logging in to Amazon KDP or publishing automatically. PBS produces a handoff package and instructions only.
- Claims we cannot back up: guaranteed KDP approval, global "plagiarism-free" or uniqueness guarantees, sales-rank/bestseller/demand scores, keyword search volumes, made-up prices.

## 2. User

One person: the author-operator. Technically capable (runs developer tooling) but wants normal use to need no terminal by Phase 10. Writes across genres: technical nonfiction, manuals and courses, workbooks, memoir, fiction, and serialized fiction.

## 3. Book types supported

| Type | Special needs |
|---|---|
| Nonfiction (general) | Evidence ledger, citations, bibliography, fact-check flags |
| Technical / manual / course | Code blocks, math, tables, figures, numbered captions, exercises/quizzes, glossary |
| Workbook | Exercises, fill-in prompts, worksheets, print layout with writing space |
| Memoir | Interview-to-book capture. **Never invent a personal experience.** User answers stored verbatim with provenance |
| Fiction | Story bible, characters, locations, timeline, continuity review |
| Serialized fiction / series | Shared series bible across books; per-installment exports |

## 4. Functional requirements

Priority: **P0** = MVP (Phases 01–03), **P1** = writing/research/publishing beta (04–07), **P2** = advanced (08), **H** = hardening/packaging (09–10). Each requirement has an ID that tests and `docs/FEATURE_MATRIX.md` (Phase 09) trace back to.

### 4.1 Library and projects (P0)
- FR-LIB-1 Create, open, rename, archive/unarchive and duplicate projects. Permanent deletion is a separate, explicit, confirmed action.
- FR-LIB-2 Project metadata: title, subtitle, project type, language (BCP-47), intended audience, target word count, publication formats (ebook / paperback / hardcover), author or pen name.
- FR-LIB-3 Search projects by title and sort by title, type, language, updated date and target word count.
- FR-LIB-4 The dashboard shows real projects and recent activity only. Demo data comes from a separate seed script and is never mixed in silently.

### 4.2 Manuscript and editor (P0)
- FR-MS-1 Ordered chapter/section tree. Reorder, rename, edit slugs, word counts, per-chapter targets, status (`planned → draft → in_review → approved`) and lock.
- FR-MS-2 Editing with a Markdown source view plus a rendered preview (Phase 02 picks the editor component; see ADR-0002, to be written). Required structures: headings H1–H6, paragraphs, ordered/unordered/task lists, block quotes, links, tables, fenced code with language, images with **separate alt text and caption**, inline and display math (LaTeX), footnotes, citations `[@key]`, explicit anchors/IDs.
- FR-MS-3 Lossless round trip: editor ⇄ storage ⇄ Markdown/HTML export must not silently drop any required structure. If something cannot be represented, the user gets an explicit warning before saving or exporting.
- FR-MS-4 Autosave with conflict protection (optimistic concurrency on the revision number), plus manual save and named checkpoints.

### 4.3 Versioning, compare, restore, backup (P0)
- FR-VER-1 Every change, human or AI, creates an immutable chapter revision recording its origin (human, AI-generated, AI-assisted, imported, restored), author action, job ID and model if any.
- FR-VER-2 Side-by-side and inline diff between any two revisions.
- FR-VER-3 Restore creates a **new** revision copied from the old one. History is never rewritten.
- FR-VER-4 Project backup to ZIP with a manifest (schema version, checksums), and restore into a **new** project. Restore never silently overwrites an existing project.

### 4.4 Import (P0 for Markdown/TXT; P1 for DOCX/HTML/PDF)
- FR-IMP-1 Import Markdown, TXT, DOCX, HTML and text-based PDF into a new or existing project.
- FR-IMP-2 Original uploads are stored byte-for-byte, are immutable and are content-addressed (SHA-256).
- FR-IMP-3 Show an import preview first: detected chapters, structure, duplicates and unsupported content. Write an import report.
- FR-IMP-4 Detect scanned or image-only PDFs and warn clearly that text extraction fails without OCR (OCR is an optional later feature). Lossy conversions are labeled as lossy.
- FR-IMP-5 Protect against script injection, unsafe links, zip bombs, path traversal, oversized and encrypted files.

### 4.5 AI providers and jobs (P0)
- FR-AI-1 Provider adapters: Ollama (local), OpenAI, Google Gemini, Anthropic, Groq. Model lists are discovered or entered by the user. Capabilities are checked, never assumed.
- FR-AI-2 Privacy mode is shown at all times: **Local-only** (default) or **Cloud allowed**. Local-only fails closed: no cloud call is ever made, and there is no automatic fallback from local to cloud.
- FR-AI-3 Routing by task (brainstorm, research, outline, draft, revise, summarize, translate). An explicit choice overrides the defaults.
- FR-AI-4 Keys live in the OS credential store only.
- FR-AI-5 Before large jobs, show estimated tokens and cost, labeled as **estimates**. Record actual usage when the provider reports it. Unknown prices show as "unknown", never as a guess.
- FR-AI-6 Durable background jobs: they survive restart, can be cancelled, retried and resumed, run with bounded concurrency, and never commit their final result twice. There is a status center with per-job logs.
- FR-AI-7 AI output goes to a review pane as a **proposal**. Accepting it creates a revision. AI never overwrites approved or locked content.

### 4.6 Knowledge, evidence and voice (P1)
- FR-KB-1 Per-book and opt-in shared knowledge libraries: import, deduplicate, index, tag, enable/disable, remove, reindex.
- FR-KB-2 FTS5 search with highlighted passages. Optional local-embedding semantic search behind a capability flag, with visible match reasons.
- FR-KB-3 Grounded generation: the model receives chunk IDs. Every claim links to exact source passages, or carries an explicit **Unverified** flag.
- FR-KB-4 Evidence ledger, kept separate from prose: claim text, supporting source chunks, review state and citation key.
- FR-KB-5 Source records hold: title, document or URL, retrieval time (UTC), stable ID, page/location where available, and content hash.
- FR-KB-6 Author voice profiles, built only from writing the user owns or has rights to. Editable style guide. Style rewrites are preview-only until accepted.
- FR-KB-7 Interview-to-book: verbatim answers with provenance. AI may structure and edit them but may not invent experiences.

### 4.7 Research and planning (P1)
- FR-PLN-1 New Book wizard (type, audience, purpose, promise, tone, author profile, genre, length, language, chapter count, sources, formats, approval preference).
- FR-PLN-2 Research workspace. Public-source search adapters run only when configured. Findings capture source, date and URL. Heuristic observations are visually separate from measured evidence.
- FR-PLN-3 Book brief: target reader, core promise, exclusions, value proposition, teaching or plot arc, and explicit assumptions.
- FR-PLN-4 Outline builder with stable section IDs: reorder, merge/split, goals, target words. Outlines need approval before bulk generation.
- FR-PLN-5 Budget cap (currency and token) plus a chapter-count cap per run. Modes: outline-only, one chapter, entire book.

### 4.8 Writing pipeline and reviews (P1)
- FR-WR-1 Section-level drafting with scoped context (brief, local outline, prior summaries, style guide, retrieved passages, story bible) and an explicit token budget.
- FR-WR-2 Selection actions: rewrite, expand, shorten, change tone, clarify, remove repetition, improve transitions, explain, and generate exercises/quizzes/glossary entries. Every action shows a diff and asks to accept or reject.
- FR-WR-3 Quality checks: grammar and style, repeated phrases, duplicated internal content, unsupported claims, missing citations, outline mismatch, broken links, missing alt text, inconsistent terms, undefined acronyms.
- FR-WR-4 Fiction continuity: chronology, character traits, locations, relationships, unresolved threads.
- FR-WR-5 Originality report with a stated scope: local duplicate and overlap detection only, plus optional authorized similarity providers. The UI says plainly that finding no match is **not** proof of uniqueness or non-infringement.

### 4.9 Design, export and publishing (P1)
- FR-PUB-1 Front and back matter templates. ISBNs, endorsements and legal statements are never fabricated; the user supplies them.
- FR-PUB-2 Interior templates (novel, nonfiction, technical, workbook): trim size, fonts with license notes, headers and footers, mirrored margins and gutter, TOC, figure and table numbering.
- FR-PUB-3 Exports: Markdown, HTML, DOCX, EPUB 3 and print-interior PDF. MOBI/AZW3 is an optional external conversion, clearly labeled; it is not native and KDP does not require it.
- FR-PUB-4 Cover designer: licensed artwork or an image provider, with **typography rendered as editable text layers**, not lettering generated by the image model. Ebook front cover plus print full wrap (back + spine + front), recalculated from the final page count against a versioned specification table that cites its source and date.
- FR-PUB-5 Preflight report saved with each export: PDF page size and count, bleed and margins, font embedding, image effective PPI, EPUB nav/metadata/links, DOCX validity, EPUBCheck result when installed. When a validator is missing, the report says **"validation unavailable"**, never "passed".
- FR-PUB-6 Publishing handoff package: exports, covers, metadata JSON and text, up to seven editable keyword fields, category suggestions marked unverified, AI-disclosure checklist, sources, license notes, and manual KDP upload and preview steps.

### 4.10 Advanced (P2)
- FR-ADV-1 Series workspace and shared story bible, with canon (approved) kept distinct from AI suggestions.
- FR-ADV-2 Author / pen-name profiles.
- FR-ADV-3 Translation into linked, independent localized editions. The original is never modified.
- FR-ADV-4 Optional narration (TTS) and transcription of interviews, using only providers the user has configured explicitly.
- FR-ADV-5 Market and keyword research using licensed data sources only. Without one, PBS offers brainstorming labeled as heuristic.

### 4.11 Cross-cutting UX (all phases)
- FR-UX-1 Every block of prose carries a visible origin and approval badge, distinguishing **AI suggestion**, **human-approved text**, and **generated source claim**.
- FR-UX-2 A data-sharing indicator is always visible (Local-only / Cloud allowed, plus an indicator while a cloud call is active).
- FR-UX-3 Activity log of user-visible events (no secrets).
- FR-UX-4 Progress is shown as stages; percentages appear only when real numbers exist. Cancel, retry and resume are available wherever a job is running.
- FR-UX-5 Accessibility: WCAG 2.2 AA target, full keyboard operation, visible focus, labeled controls, live-region announcements for errors and job status, reduced-motion support.
- FR-UX-6 Features from later phases are shown **disabled and labeled "Not yet available (Phase NN)"**. Nothing pretends to work.

## 5. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-1 Privacy | No network egress except (a) cloud AI/research providers the user enabled, (b) explicit user-initiated actions. A test asserts zero egress in local-only mode. |
| NFR-2 Durability | No acknowledged write is lost after a crash: SQLite WAL, `synchronous=FULL` for revision commits, atomic file writes (temp file + fsync + rename). |
| NFR-3 Integrity | Revisions and originals are immutable at the DB level (triggers). Assets are checksummed. |
| NFR-4 Performance targets (to be measured, Phase 09) | 100 chapters, ~500 assets, ~10k source chunks: library opens in under 2 s, FTS query returns in under 300 ms, editor keystroke latency under 50 ms, full EPUB export in under 60 s on the dev machine. These are targets, not claims. |
| NFR-5 Portability | Windows 11 x64 first (the dev machine), then macOS (Apple Silicon and Intel). Linux is best effort. |
| NFR-6 Recoverability | Automatic DB backup before every schema migration. One-click project backup ZIP. |
| NFR-7 Observability | Structured JSON logs on local disk, with secrets redacted by a central filter; log rotation. |
| NFR-8 Licensing | Every bundled dependency's license is recorded. No AGPL dependencies in the shipped app without an ADR. |

## 6. Governance (non-negotiable; enforced by tests)

1. The user owns the work. Originals are immutable. Destructive actions require an explicit, confirmed user action.
2. AI never silently overwrites approved or locked content. AI writes **proposals**; only an explicit accept creates a revision.
3. External sources and imported documents are **untrusted data**. They are prompt-injection surfaces and can never issue instructions or trigger tool use.
4. Attribution includes document or URL, retrieval time, stable ID and location. Unsupported claims are flagged, never turned into citations.
5. Local-only mode fails closed.
6. Credentials live only in the OS credential store. They never appear in logs, Git, exports, backups or DB plaintext.
7. The originality report states its limits.
8. AI-generated vs AI-assisted content is tracked per revision and per block, and feeds the KDP disclosure checklist.
9. No automatic KDP login or publishing.
10. No fabricated citations, scores, search volumes, costs or provider capabilities.

## 7. Success criteria (personal release)

The user can create or import a book, draft and edit it with local AI, inspect citations and history, preview it, export validated EPUB/DOCX/PDF, assemble a KDP handoff package, and recover from backup, all without a terminal during normal use (Phase 10). Every unsupported feature is visibly labeled.

## 8. Open product questions (see BUILD_STATE "Decisions requiring validation")

- Default data folder location (Documents vs AppData).
- Whether a WYSIWYG editor is wanted, or Markdown source + preview is enough (it is lossless by construction).
- Which licensed market-data sources, if any, the user can access (otherwise market research stays heuristic only).
- Which image-generation and TTS providers, if any.
