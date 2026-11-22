# Personal Book Studio — Build State

> Single source of truth for "where are we". Every phase ends by updating this file with **evidence** (commands + real results).

## Current status

| Field | Value |
|---|---|
| Current phase | **01: Scaffold, shell, project library, vertical slice: COMPLETE (pending user review)** |
| Next phase | 02: Editor, BookMD/BDM fidelity, revisions/diff/restore, imports, backup/restore, export-engine spikes |
| Branch | `phase/01-scaffold` (from `main` @ Phase 00 docs) |
| Platforms verified | Windows 11 x64 only. macOS scripts (`*.sh`) are written but **not executed** (no Mac available) |
| Last updated | 2026-11-22 |

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

### Phase 01: Scaffold and vertical slice (2026-11-22)
- Built backend, frontend, scripts and tests as described above, on branch `phase/01-scaffold`.
- Verified in a real browser (in-app pane): create book → add chapter → type → Ctrl+S → library card shows 10 words and 1 chapter.
- Fixed during the phase: menu-toggle CSS specificity, the library filter row overflowing at 1024px, a privacy-badge contrast failure (axe), openapi-fetch capturing `fetch` at import time (broke test mocking), and Windows console encoding in the license gate and OpenAPI export.

### Phase 00: Planning (2026-11-22)
- Inspected the repo and environment. Created PRD, ARCHITECTURE, DATA_MODEL, SECURITY, ADR-0001, TEST_PLAN, ROADMAP and BUILD_STATE plus `.gitignore` and `.gitattributes`. Committed and pushed to `main`.

## Environment snapshot (2026-11-22)

Windows 11 Pro for Workstations x64. git 2.50.1, gh 2.96.0. Python default 3.15.2 (**not used**), 3.13.1, 3.12.13 (uv). uv 0.11.15 (needs `UV_LINK_MODE=copy`). Node 26.13.0, pnpm 10.33.0. Rust 1.95.0 (MSVC host), VS BuildTools present, WebView2 157. Docker 29.9.2. Playwright 1.65 / Chromium 1255 cached.
**Missing (not needed until later phases):** Pandoc, Java/EPUBCheck, Ollama, GTK/Pango (WeasyPrint), Tesseract, Calibre, Typst CLI.
