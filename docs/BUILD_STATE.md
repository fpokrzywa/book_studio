# Personal Book Studio — Build State

> Single source of truth for "where are we". Every phase ends by updating this file with **evidence** (commands + real results).

## Current status

| Field | Value |
|---|---|
| Current phase | **02: Editor, document model, history, imports, backup/restore: COMPLETE (pending user review)** |
| Next phase | 03: AI providers, egress gate, keyring, routing, cost, durable jobs, proposals |
| Branch | `phase/02-editor-import-backup`, stacked on `phase/01-scaffold` (PR #1, not merged yet) |
| Schema | Alembic head `0003`. The existing dev workspace migrated 0002 → 0003 automatically with a snapshot |
| Platforms verified | Windows 11 x64 only. macOS scripts are written but **not executed** |
| Last updated | 2026-11-22 |

## Phase 02 evidence (real results, 2026-11-22, Windows 11, CPython 3.12.13, Node 26.13)

Command: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1` → **exit 0, "All checks passed."**

| Check | Result |
|---|---|
| ruff lint / format (Core) | All checks passed / 73 files already formatted |
| mypy `--strict` (51 source files) | Success: no issues found |
| import-linter | 3 kept, 0 broken |
| pytest (Core) | **135 passed, 8 xfailed** (8 = golden-path steps owned by Phases 03–07, strict xfail) |
| License gate | passed: 83 runtime dependencies (adds mammoth BSD-2, pypdf BSD-3, nh3 MIT, latex2mathml MIT, python-multipart Apache-2.0, defusedxml PSF, CodeMirror MIT) |
| ESLint (jsx-a11y strict) + Prettier, TypeScript strict | clean |
| Vitest + RTL + axe-core | **18 passed** (5 files) |
| Vite production build | built |
| Playwright + axe (WCAG 2.2 AA tags) | **7 passed** (2 new Phase 02 specs + 5 Phase 01 specs adapted to the new editor) |

### Prompt 02 acceptance → evidence

| Acceptance item | Where it is proven |
|---|---|
| Import a multi-chapter fixture with a table, image/caption, code block, citation and math; edit; save; restart; round-trip; verify preservation | `tests/test_acceptance_phase02.py` (API, with a real restart of the app context), and Playwright `manuscript.spec.ts` (UI import → edit in CodeMirror → **hard-kill Core** → reload → recovered draft + saved revision → exports) |
| Restore a previous revision; the newer revision remains in history | same two tests, plus `test_manuscript.py::test_restore_creates_new_revision_and_keeps_history` |
| Reorder chapters; content/asset/citation references stay stable | `test_manuscript.py::test_reorder_does_not_orphan_references`, the acceptance test (re-parent + reorder + HTML export resolves image and citation), Playwright (buttons **and** drag-and-drop) |
| Backup → restore gives an equivalent manuscript and metadata | `test_backup.py::test_backup_then_restore_is_equivalent_and_never_overwrites` (compares every chapter, revision, label, note, draft, tree position, asset and metadata field), Playwright (UI backup download → Library restore) |
| Canonical schema round-trips without silent loss | `test_document_engine.py`: kitchen-sink fixture, plus a **150-example hypothesis property test** of serialize→parse identity. It found and fixed two real bugs: braces/quotes in attribute values, and tight-list item joining |
| Unsafe links, script injection, zip bombs, path traversal, size limits, encrypted/unreadable files | `test_imports.py` (scanned/encrypted PDF, legacy .doc, zip bomb, traversal, XXE, injection HTML, 413 over the limit, SVG refused), `test_backup.py` (tampered checksum, unlisted file, missing manifest, newer schema, unsafe archive paths, not-a-zip), Playwright "hostile and unreadable files" |
| Originals preserved, import reports, duplicates | `test_imports.py` (byte-identical download, DB immutability triggers, `previously_imported_at`, same-text and same-title duplicate detection) |

## Phase 02: what was built

**Core**
- `document/bookmd.py`: bookmd-1 → `bdm/1` (headings with anchors, paragraphs, tight/loose and task lists, quotes, GFM tables with alignment and captions, fenced code with language and attributes, inline and display math with labels, footnotes, citations with locators and author suppression, figures with alt ≠ caption, fenced divs, unsupported blocks kept verbatim). Fidelity warnings: missing alt, web/unresolved images, missing footnotes, duplicate anchors, unsafe links.
- `document/serialize.py` (normal-form writer, used by imports) and `document/html.py` (renderer + nh3 sanitizer, MathML via latex2mathml, inert unsafe links, no external image loads).
- Migration `0003`: originals, imports, assets, drafts, revision tags, project description, export formats, original-file immutability triggers.
- Services: chapter tree (part/chapter/section, max depth 3) and move/reorder; slug, title, status, kind and target edits; subtree archive; autosave drafts with conflict detection; revision list/get/compare (side-by-side, word-level)/restore-as-new/tag; preview; assets (content-addressed raster images); exports (Markdown or Markdown+images ZIP; standalone HTML with embedded images and a CSP); imports (md, txt, html, docx via mammoth, text PDF via pypdf); backup ZIP (manifest/1) and restore-as-new-project with ID remapping.
- `security/archive.py` (zip inspection, capped reads, DTD/XXE rejection); chunked upload limits (413).
- `fixtures/generate.py` and checked-in synthetic fixtures.

**UI**
- Book page: manuscript tree with drag-and-drop **and** Up/Down/Indent/Outdent buttons, chapter details (title, slug, status, target), nesting with progress bars, Markdown/HTML export, backups, and Import chapters.
- Editor: CodeMirror 6 source editor (Tab not captured) with a plain-textarea mode; Write / Write and preview / Preview views; Core-rendered preview with formatting notes; autosave drafts with recovery and stale-draft banners; Save/Ctrl+S; conflict dialog; a leave guard that offers "keep as draft" or "save revision"; Insert image (alt text required); History dialog (labels and notes, side-by-side diff using `<del>`/`<ins>`, restore as new); chapter quick-nav with previous/next.
- Import page (file input + drop zone, target book, preview with warnings, lossy notice, duplicates, per-chapter include, commit or cancel) and Library "Restore a backup".
- Navigation: **Import** added. Help text updated.

**Docs:** ADR-0002 (editor), ADR-0003 (export-engine spikes), plus as-built notes in DATA_MODEL, ARCHITECTURE, SECURITY, TEST_PLAN, ROADMAP and README.

## Decisions taken in Phase 02 (need your validation)

| # | Decision | Why | Reversible? |
|---|---|---|---|
| P2-1 | Source editor (CodeMirror) + Core preview instead of WYSIWYG (ADR-0002) | Lossless by construction; one renderer | Yes. A WYSIWYG must pass the fidelity suite first |
| P2-2 | Autosave writes a **draft** (mutable working copy). Only Save/restore/import create revisions | Keeps history meaningful (not one revision per keystroke) while never losing typing | Yes |
| P2-3 | Images referenced by **content hash** (`asset:<16 hex>`) | Duplicate, backup and restore need no text rewriting | Costly to change later |
| P2-4 | Originals stored workspace-wide (not per project), content-addressed, read-only | An upload exists before its project; dedupe | Yes |
| P2-5 | Restore always creates a new project titled "… (restored)", set to active | "No silent overwrite" | Yes |
| P2-6 | PDF import is text only and always marked lossy; scanned PDFs are refused (no OCR) | Honest about limits | Yes, later |
| P2-7 | Recommend **Typst** as the Phase 07 print-PDF engine (ADR-0003, D7) | WeasyPrint failed without GTK on Windows; the Typst wheel works offline | Decide in Phase 07 |

Still open from earlier: D6 (install Pandoc), D12 (public repo), D14 (prompt pack location), LICENSE choice.

## Known limitations (Phase 02, honest list)

1. **No WYSIWYG.** Writers edit Markdown with a live preview (ADR-0002).
2. **Word equations are not imported** (mammoth cannot convert OMML). They are detected and reported. Pandoc-based import would fix this (D6).
3. **PDF import recovers text only.** Headings are guessed from "Chapter …" lines; tables, images and footnotes are lost (reported). No OCR.
4. **HTML/DOCX import limits:** merged table cells are split (reported); sub/superscript and definition lists become plain text (reported); display math inside a paragraph becomes inline math.
5. **Citations are kept as keys.** Rendering is `(key, locator)`; bibliography formatting and key resolution arrive in Phase 04.
6. **No standalone annotation table** (comments on blocks). Revision labels and notes cover "revision labels and notes"; block annotations are deferred.
7. **Autosave conflict handling is last-writer-wins between two open tabs on the same base revision.** A later Save in either tab is still protected by the 409 check.
8. Drag-and-drop reorders among siblings and adopts the target's parent; nesting is done with Indent/Outdent. A drop "into" a chapter is not offered.
9. The footnote back-link renders on its own line in the preview (cosmetic).
10. macOS has not been run. Linux has not been run.
11. EPUB, DOCX and print PDF exports are Phase 07.
12. The stray `.pbs-test-run.log` from Phase 01 may still be at the repo root (git-ignored).

## Phase 03 handoff

Preserve: the `/api` contracts (regenerate TS with `scripts/gen-api`); the revision triggers (the AI-origin rule already requires `accepted_proposal_id`, which Phase 03's `proposal` table must satisfy); drafts are **not** revisions; `bookmd`/`bdm/1` invariants and the property test; `security/archive.py` and the upload caps; the import determinism check at commit.

Start Phase 03 with: the `proposal` and `job` tables (migration 0004); the egress gate before any HTTP client (keep the import-linter contract, adding an exception only for `pbs_core.providers`); the mock provider first; and AI output written as a proposal diffed against the head revision, using the same side-by-side diff component as History.

---

## Phase 01 evidence (real results, 2026-11-22, Windows 11, CPython 3.12.13, Node 26.13, pnpm 10.33)

Command: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1` → **exit 0, "All checks passed."**

| Check | Result |
|---|---|
| ruff lint / format (Core) | All checks passed / 54 files already formatted |
| mypy `--strict` (37 source files) | Success: no issues found |
| import-linter (3 contracts: pure domain/document, no network clients, layering) | 3 kept, 0 broken |
| pytest (Core) | **97 passed, 12 xfailed** (xfails = E2E-GOLDEN-01 steps owned by later phases, strict) |
| License gate (`scripts/check_licenses.py`) | passed: 53 runtime dependencies checked, no AGPL/GPL/SSPL/unknown |
| ESLint (incl. jsx-a11y strict, no `dangerouslySetInnerHTML`) + Prettier | clean |
| TypeScript (`tsc`, strict, app + node configs) | clean |
| Vitest + React Testing Library + axe-core | **11 passed** (3 files) |
| Vite production build | built |
| Playwright (Chromium 159) + @axe-core/playwright | **5 passed** |

Note: the first full run printed 96 pytest passes. `test_golden_path.py` was added afterwards and run separately: 1 passed, 12 xfailed. The full count above includes it.

### What the tests prove (mapped to the Phase 01 gates in ROADMAP.md)

| Gate | Evidence |
|---|---|
| G1.1 documented start commands | `scripts/dev.ps1` started Core + UI and the app was used in the browser (create book, add chapter, type, Ctrl+S → "Saved as revision 1", library card). The README lists the exact commands |
| G1.2 guard | `test_security.py`: no token → 401, wrong token → 401, bad Host / DNS-rebinding Host → 400, foreign Origin → 403 even with a token, `Sec-Fetch-Site: cross-site` → 403, no CORS headers ever, non-loopback `PBS_HOST` refused. `test_process_restart.py`: a real process listens on loopback only (netstat) |
| G1.3 migrations + immutability | `test_migrations.py`: fresh → head; head → head is a no-op; 0001 → 0002 with data preserved and a pre-migration snapshot; a newer DB is refused; models ≡ migrations (no drift). `test_chapters.py`: UPDATE/DELETE of revisions, AI-origin revision without a proposal, and non-sequential revision numbers are all rejected **by SQLite triggers**; composite FKs reject cross-project references |
| G1.4 CRUD + search/sort | `test_projects.py`: create/read/rename/edit, validation (no input echo), search over title/subtitle/audience/author with Unicode case-folding and LIKE escaping, filter by type/language/format, sort by title/type/language/audience/target/updated with nulls last, archive (read-only) and unarchive, duplicate (heads copied as revision 1, history not copied, original untouched) |
| G1.5 vertical slice | Playwright `vertical slice`: create book → add chapter → type a table, a tab/trailing-space code block, math and a citation → Save → **hard-kill Core and restart it** → reload → identical text → Export Markdown → downloaded file contains the chapter byte-for-byte. Also `test_process_restart.py` (real process kill/restart via API) |
| Isolation | `test_chapters.py::test_project_isolation_through_api` (404 for cross-project IDs, exports contain only their own project), DB-level composite FK test, Playwright `project isolation` |
| G1.6 navigation | Library, New book, Manuscripts, Activity and Help work. Research, Knowledge, Publishing and AI settings are `aria-disabled` and labeled "Not yet implemented (Phase NN)"; their URLs show an explicit not-implemented page (Vitest + Playwright) |
| G1.7 privacy badge | "Local-only" in the top bar, served from `/api/system/info` |
| G1.8 accessibility | axe: no serious/critical violations on library, new book, project and editor pages (Playwright, WCAG 2.2 AA tags). A real contrast failure on the privacy badge was found and fixed. A keyboard-only flow passes |
| Logging/redaction | `test_logs_never_contain_secrets`: canary keys in fields, messages and tracebacks never reach `logs/core.jsonl` |
| No external network | Session-wide pytest socket guard (non-loopback connect → error + test-suite failure). Import contract forbids network client libraries in `pbs_core`. The UI bundles fonts (no CDN) |

## What was built in Phase 01

**Backend (`apps/studio-core`, package `pbs_core`)**
- `config.py`: `PBS_*` settings. Host is forced to loopback; workspace resolution (dev `./.pbs-data`, prod `Documents/Personal Book Studio`).
- `storage/`: workspace layout, `safe_join` (absolute/drive/UNC/`..`/ADS/reserved names/trailing dots/symlink escapes), `sanitize_filename`, `slugify`, atomic writes; SQLite engine policy (WAL, `synchronous=FULL`, `BEGIN IMMEDIATE`, `pbs_fold`); models; programmatic Alembic migration with quick_check + online-backup snapshot + newer-DB refusal; `backup_manifest.py` (manifest/1 schema with safe archive paths).
- `migrations/`: `0001_baseline` (tables + 4 integrity triggers) and `0002_backup_run`.
- `security/`: per-launch 256-bit session token in `runtime/session.token` (runtime dir ACL restricted to the current user's SID via `icacls` on Windows, 0700/0600 on POSIX); ASGI guard; redaction processor.
- `logging_setup.py`: structlog JSON with redaction applied last, also for uvicorn and stdlib logs.
- `document/bookmd_v0.py`: lossless provisional parser (`bdm/0`), with block-ID reuse for unchanged blocks.
- `domain/`: ULIDs (monotonic), fractional position keys (property-tested), word count, typed domain errors.
- `services/`: projects, chapters (optimistic concurrency, approved-chapter lock, no-op on identical save), Markdown export (`pbs-md-export/1`), activity, capability detection (PATH lookup only).
- `api/`: problem+json errors (never echo input), routes per BUILD_STATE plan, app factory; `python -m pbs_core`; `pbs_core.openapi_export`; `pbs_core.tools.seed_demo` (explicit, labeled demo data).

**Frontend (`apps/studio-ui`)**: an original "bindery" design. Cool endpaper surfaces, blue-black ink, bookcloth spine colors per kind of book, a gilt ribbon whose length is real progress toward the target word count. Literata for manuscript and headings, Atkinson Hyperlegible for UI. Light and dark themes, reduced motion, responsive (drawer nav below 52rem). Pages: Library (search, filters, sort, active/archived/all, recent activity), New book, Project (details, edit dialog, duplicate, archive/unarchive, chapters with add/rename/archive, Markdown export with download and warnings, per-book history), Chapter editor (Markdown textarea, status, Save + Ctrl/Cmd+S, unsaved-changes guard for in-app navigation and tab close, 409 conflict dialog, approved-chapter lock with "Reopen for editing"), Manuscripts, Activity, Help (privacy explanation, workspace path, detected optional tools), not-implemented pages. Route-level error boundary, live-region toasts, skip link.

**Tooling**: `scripts/setup|dev|test|gen-api` (`.ps1` + `.sh`), `scripts/check_licenses.py`, Playwright fixtures that spawn and hard-kill a real Core, README with Windows/macOS commands and troubleshooting.

## Decisions taken in Phase 01 (defaults applied; the user had not answered D1–D14)

| # | Decision applied | Reversible? |
|---|---|---|
| D1 | CPython 3.12 (uv) | Yes (ADR) |
| D2 | Dev workspace `./.pbs-data` (git-ignored); prod default `Documents/Personal Book Studio` | Yes, via `PBS_WORKSPACE` |
| D3 | Core 127.0.0.1:8765, UI 127.0.0.1:5173 (both overridable) | Yes |
| D5 | Single `studio.db` with composite-FK isolation | Costly after Phase 02 |
| new | TypeScript 6.0 + ESLint 9 instead of TS 7 / ESLint 10 (plugin compatibility; ADR-0001 §7a) | Yes |
| new | Library search = case-folded substring, not FTS5 (DATA_MODEL §2.1) | Yes |
| new | `synchronous=FULL` always, rather than per-commit switching | Yes |
| new | API contract lives in `apps/studio-ui/src/api/` rather than `packages/contracts` | Yes |

Still open for the user: **D12** (the repo is public), **D14** (move the prompt pack to `docs/BUILD_PROMPTS.md`), a **LICENSE** choice (none added; currently "all rights reserved" by default), and D6–D11 for later phases.

## Known limitations (honest list)

1. **Editor is a plain Markdown textarea.** There is no preview, no autosave (manual Save / Ctrl+S only) and no formatting toolbar. The editor choice is ADR-0002 in Phase 02.
2. **Revision history has an API but no UI** (`GET …/revisions`). Diff and restore UI arrive in Phase 02.
3. **bookmd-0.1 models only top-level blocks.** Tables, math, footnotes, citations and attributes are preserved verbatim in the source and in block `src`, but they are not structured yet (`bdm/0`).
4. **No chapter reordering yet.** Positions are fractional keys ready for it (Phase 02).
5. **Backup:** only the data structure exists (manifest/1 schema, `backup_run` table) plus automatic pre-migration DB snapshots. The ZIP backup/restore flow is Phase 02.
6. **No imports** (Markdown/DOCX/HTML/PDF): Phase 02.
7. **Archive is the only removal action.** There is no permanent purge yet (by design; the `_purge_ctx` hook exists).
8. **macOS not verified.** `dev.sh`, `setup.sh` and `test.sh` have not been run. Keychain and ACL behavior on macOS are untested.
9. **The UI is dev-server only.** Core does not serve the built UI. A packaged runtime is Phase 10.
10. gitleaks is not installed locally, and there is no CI yet. The secret scan relies on `.gitignore` plus redaction tests.
11. The Vitest axe runs exclude `color-contrast` (jsdom cannot compute colors). Contrast is enforced in Playwright.
12. The Starlette TestClient's httpx deprecation warning is filtered in tests. Revisit when Starlette removes it.
13. The `preview_start` launcher (`.claude/launch.json`) did not start the script in the desktop app's browser pane. Running `scripts/dev.ps1` directly works.
14. A stray local log file `.pbs-test-run.log` may exist at the repo root from the evidence run. It is git-ignored (`*.log`) and safe to delete.

## Phase 02 handoff

Contracts to preserve: the `/api` routes and Pydantic contracts in `contracts.py` (extend, don't break; regenerate with `scripts/gen-api`); the revision immutability triggers; composite FKs; `expected_head_no` optimistic concurrency; the `pbs-md-export/1` format; the guard (token/Host/Origin); and the `safe_join`/`sanitize_filename` usage for every path.

Start Phase 02 with:
1. **bookmd-1 / `bdm/1`** per DATA_MODEL §4 (tables, math, footnotes, citations, attributes, figures with alt ≠ caption, divs). Add upcast from `bdm/0` by re-parsing `source_md`, plus the hypothesis round-trip suite and the `kitchen-sink.md` fixture.
2. **ADR-0002 editor bake-off** (CodeMirror 6 source mode as the leading candidate) and a server-rendered preview using one renderer shared with export.
3. **Revision UI**: list, diff (word-level), restore as a new revision with `origin=restored`, labels and notes, plus autosave with the existing 409 protection.
4. **Chapter reorder** (keyboard-accessible) using `key_between`.
5. **Imports** with preview, immutable `original_file`, import reports, and the malicious fixtures (zip bomb, XXE, traversal, XSS, encrypted/scanned PDF).
6. **Backup ZIP / restore-as-new** using `BackupManifest` (manifest/1) and `backup_run`.
7. **Spikes → ADR-0003**: WeasyPrint on Windows (Pango) vs Typst vs Chromium; ziamath/latex2mathml math; Pandoc DOCX via the BDM → Pandoc AST writer. (Pandoc, Java and GTK are still not installed on this machine.)

---

## Phase log

### Phase 02: Editor, document model, history, imports, backup (2026-11-22)
- Built as described in "Phase 02: what was built" on `phase/02-editor-import-backup` (a WIP checkpoint commit, then a final commit).
- Verified in the real browser by hand (imported fixture → tree → editor split view with rendered math, citation, figure caption and footnotes) and with Playwright.
- Bugs found and fixed during the phase:
  - the property test found two serializer bugs (attribute values containing braces or quotes; tight lists with nested blocks);
  - the dollarmath plugin's first-character digit check (replaced by a currency guard);
  - inline-image alt text was lost;
  - explicit alt text set by the attrs plugin was ignored;
  - nested-transaction deadlock when an import created a project (moved project creation into the same transaction);
  - empty `<ins>` elements in the diff view;
  - axe: the scrollable diff region was not keyboard-focusable;
  - read-only originals blocked the e2e workspace wipe.
- Spikes recorded in ADR-0003.

### Phase 01: Scaffold and vertical slice (2026-11-22)
- Built backend, frontend, scripts and tests as described above, on branch `phase/01-scaffold`.
- Verified in a real browser (in-app pane): create book → add chapter → type → Ctrl+S → library card shows 10 words and 1 chapter.
- Fixed during the phase: menu-toggle CSS specificity, the library filter row overflowing at 1024px, a privacy-badge contrast failure (axe), openapi-fetch capturing `fetch` at import time (broke test mocking), and Windows console encoding in the license gate and OpenAPI export.

### Phase 00: Planning (2026-11-22)
- Inspected the repo and environment. Created PRD, ARCHITECTURE, DATA_MODEL, SECURITY, ADR-0001, TEST_PLAN, ROADMAP and BUILD_STATE plus `.gitignore` and `.gitattributes`. Committed and pushed to `main`.

## Environment snapshot (2026-11-22)

Windows 11 Pro for Workstations x64. git 2.50.1, gh 2.96.0. Python default 3.15.2 (**not used**), 3.13.1, 3.12.13 (uv). uv 0.11.15 (needs `UV_LINK_MODE=copy`). Node 26.13.0, pnpm 10.33.0. Rust 1.95.0 (MSVC host), VS BuildTools present, WebView2 157. Docker 29.9.2. Playwright 1.65 / Chromium 1255 cached.
**Missing (not needed until later phases):** Pandoc, Java/EPUBCheck, Ollama, GTK/Pango (WeasyPrint), Tesseract, Calibre, Typst CLI.
