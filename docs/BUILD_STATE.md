# Personal Book Studio — Build State

> Single source of truth for "where are we". Every phase ends by updating this file with **evidence** (commands + real results).

## Current status

| Field | Value |
|---|---|
| Current phase | **00: Planning: COMPLETE (pending user review)** |
| Next phase | 01: Scaffold, shell, project library, vertical slice |
| Code written | None. Only documentation (and `.gitignore`) |
| Tests | None yet (nothing to run) |
| Repo | Local `S:\Development_2026\book_studio`, git initialized, remote `origin` → `https://github.com/fpokrzywa/book_studio.git` (public). Phase 00 docs committed and pushed to `main` |
| Last updated | 2026-11-22 |

## Phase 00 deliverables

| Doc | Contents |
|---|---|
| `docs/PRD.md` | Scope, non-goals, clean-room statement, functional requirements with IDs (FR-*), NFRs, governance rules |
| `docs/ARCHITECTURE.md` | System and data-flow diagrams (Mermaid), module layout, workspace boundaries, on-disk layout, document engine, export pipeline, job system, provider layer, frontend, logging, desktop preview, **risk register (R1–R20)** |
| `docs/DATA_MODEL.md` | Conventions, ER diagram, all core tables by phase, **state machines** (project, chapter, revision, proposal, job, import, export, claim, canon), **BookMD + BDM editing schema** with invariants, **migration strategy**, backup format |
| `docs/SECURITY.md` | Threat model, local API guard, credentials, egress gate/privacy modes, prompt-injection isolation, data handling, public-repo hygiene, per-phase security checks |
| `docs/ADR/0001-stack.md` | Observed environment, stack decision, rationale, **dependency reliability + license table**, **OS blockers + fallbacks**, sidecar constraints, validation items |
| `docs/TEST_PLAN.md` | Test layers, hermetic rules, fixture catalog, key test cases, **E2E-GOLDEN-01 acceptance scenario**, phase exit evidence |
| `docs/ROADMAP.md` | Phase list, **acceptance gates per phase**, **execution checklist** |
| `docs/BUILD_STATE.md` | This file, including the **Phase 01 implementation plan** |

## Environment snapshot (2026-11-22)

Windows 11 Pro for Workstations x64. git 2.50.1, gh 2.96.0. Python default 3.15.2 (**not used**), 3.13.1, 3.12.13 (uv). uv 0.11.15. Node 26.13.0, pnpm 10.33.0. Rust 1.95.0 (MSVC host), VS BuildTools folders present, WebView2 157. Docker 29.9.2. Playwright Chromium cached.
**Missing:** Pandoc, Java/EPUBCheck, Ollama, GTK/Pango (WeasyPrint), Tesseract, Calibre, Typst CLI. None of these are needed for Phase 01.

## Decisions requiring validation (user)

| # | Decision | Default proposed | Needed by |
|---|---|---|---|
| D1 | Python pin | **3.12** via uv (3.15 system default avoided) | Phase 01 |
| D2 | Default workspace location | `Documents\Personal Book Studio` (prod); `.\.pbs-data` (dev, git-ignored) | Phase 01 |
| D3 | Dev ports | Core `127.0.0.1:8765`, UI `localhost:5173` | Phase 01 |
| D4 | Editor UX | Markdown source + preview (lossless); WYSIWYG only if it passes the fidelity suite (ADR-0002, Phase 02) | Phase 02 |
| D5 | Single `studio.db` with composite-FK project isolation (vs DB per project) | Single DB | Phase 01 |
| D6 | Install Pandoc (winget) for DOCX import/export | Recommended, optional | Phase 02 |
| D7 | PDF engine path on Windows: MSYS2 Pango vs WeasyPrint standalone exe vs Typst fallback | Decide after the Phase 02 spike | Phase 02 |
| D8 | Install Java 11+ for EPUBCheck | Optional | Phase 07 |
| D9 | Install Ollama + which local models | User choice | Phase 03 |
| D10 | Which cloud providers you actually want enabled | None by default (local-only) | Phase 03 |
| D11 | Licensed market/keyword data source, if any | None → heuristic brainstorming only | Phase 05 |
| D12 | The GitHub repo is **public**: keep it public? | Consider making it private; fixtures stay synthetic either way | Before first push |
| D13 | AI-generated vs AI-assisted classification rule (DATA_MODEL §3.3), to be checked against current KDP wording | Proposed rule; verify in Phase 07 | Phase 03 (record), 07 (verify) |
| D14 | Keep `personal_book_studio_claude_code_prompts.md` at the root or move it to `docs/BUILD_PROMPTS.md` | Move (the pack suggests it) | Any time |

## Known open risks (top 5; full register in ARCHITECTURE §11)

1. R3: PDF engine on Windows (Pango) is unproven. Spike in Phase 02.
2. R1/R2: editor fidelity and block-ID reconciliation. Gated by the fidelity suite.
3. R9: hallucinated citations. Ledger-only citation keys (Phase 04).
4. R13: public repo hygiene. `.gitignore` in place, gitleaks to be added in Phase 01.
5. R17: desktop signing/notarization. Phase 10, needs certificates the user may not have.

---

## Phase 01 implementation plan (precise)

**Goal (from prompt 01):** a real, persistent, accessible local app. Project library CRUD, chapters with content, save → restart → still there → Markdown export. Guarded loopback API. Migrations. Tests. **No external network calls.**

**Explicitly NOT in Phase 01:** revision diff/restore UI, chapter reorder, imports, preview rendering, AI, knowledge, publishing beyond Markdown, backup ZIP (the data structure is designed; implementation is Phase 02).

### Step 0: Repository bootstrap
1. Confirm git init + remote (already done in Phase 00), branch `phase/01-scaffold`.
2. Root files: `README.md`, `LICENSE` (ask the user; default "All rights reserved", since it's a personal project), `.gitignore` (exists), `.editorconfig`, `.gitattributes` (`* text=auto eol=lf`, `*.ps1 eol=crlf`, binary fixtures marked `binary`).
3. Move the prompt pack to `docs/BUILD_PROMPTS.md` if D14 is approved.

### Step 1: Backend skeleton (`apps/studio-core`)
1. `uv init --package --python 3.12 apps/studio-core`. Package `pbs_core` under `src/`.
2. Dependencies (pin compatible versions at install time and record them in the lockfile): `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `sqlalchemy>=2`, `alembic`, `structlog`, `platformdirs`, `markdown-it-py`, `mdit-py-plugins`. Dev: `pytest`, `pytest-asyncio`, `hypothesis`, `httpx`, `ruff`, `mypy`, `import-linter`, `pip-licenses`.
   - Verify that every wheel installs on CPython 3.12 win-x64 (D1). Record the results.
3. Modules to create:
   - `config.py`: `Settings` (pydantic-settings): `PBS_ENV (dev|test|prod)`, `PBS_WORKSPACE`, `PBS_HOST` (forced `127.0.0.1`; any other value → startup error), `PBS_PORT=8765`, `PBS_UI_ORIGIN=http://localhost:5173`.
   - `storage/paths.py`: `Workspace` (creates the layout from ARCHITECTURE §3.1), `safe_join`, `sanitize_filename` (Windows-reserved names, max 120 chars, NFC normalization, ASCII-fold option), `atomic_write_bytes` (temp + fsync + `os.replace`).
   - `storage/db.py`: engine factory (PRAGMAs per DATA_MODEL §1), session scope, `BEGIN IMMEDIATE` helper.
   - `storage/models.py`: SQLAlchemy models for `project`, `chapter`, `chapter_revision`, `activity_event`, `export_run`, `app_setting` (with composite FKs).
   - `migrations/`: Alembic env (`render_as_batch=True`). Revision `0001_baseline` creates the tables, FTS5 `project_fts` + sync triggers, and the immutability triggers on `chapter_revision`. Programmatic upgrade at startup with a pre-migration snapshot (online backup API) and a refusal on a newer DB.
   - `security/token.py` (generate token, write `runtime/session.token` with a user-only ACL; on Windows use `icacls` via subprocess with a fixed arg list, otherwise `os.chmod(0o600)`), `security/guard.py` (ASGI middleware: Host allowlist, Origin check on unsafe methods, `X-PBS-Token` constant-time compare; `/healthz` exempt and returns only `ok`), `security/redact.py` (structlog processor).
   - `domain/`: `enums.py`, `ids.py` (ULID generator with an injectable clock), `project_rules.py` (validation), `chapter_rules.py`, `wordcount.py`.
   - `document/bookmd_v0.py`: Phase 01 parser = markdown-it-py CommonMark → BDM blocks for `heading, paragraph, list, quote, code, thematic_break`. **Everything else** (tables, math, footnotes…) becomes an `unsupported` block holding the raw source span, `parser_version="bookmd-0.1"`. This is lossless because `source_md` stays authoritative. Phase 02 replaces it with bookmd-1.
   - `services/projects.py`, `services/chapters.py` (save = TX: check `expected_head_no`, insert revision, update head, update `project.updated_at`, insert activity), `services/exports.py` (Markdown export), `services/activity.py`, `services/capabilities.py` (PATH lookups via `shutil.which` for `pandoc`, `java`, `ollama`, `ebook-convert`, `typst`, plus an importability check for `weasyprint`. **No subprocess version calls and no network** in Phase 01; versions come in Phase 02).
   - `api/`: `app.py` (factory, lifespan: workspace + migrate + token + logging), `errors.py` (problem+json), routers below.
   - `__main__.py`: `python -m pbs_core` → uvicorn on 127.0.0.1.
4. API (all under `/api`, all require the token):

| Method & path | Purpose |
|---|---|
| `GET /healthz` (no token) | Liveness: `ok` |
| `GET /api/system/info` | App version, schema revision, workspace path, privacy mode (`local_only`) |
| `GET /api/system/capabilities` | Detected optional tools (found / not found + path) |
| `GET /api/projects?q=&sort=title\|type\|language\|updated_at\|target_word_count&order=asc\|desc&status=active\|archived\|all` | Library |
| `POST /api/projects` | Create (validated) |
| `GET /api/projects/{pid}` · `PATCH /api/projects/{pid}` | Read / rename / edit metadata |
| `POST /api/projects/{pid}:archive` · `:unarchive` · `:duplicate` | Lifecycle |
| `GET /api/projects/{pid}/chapters` · `POST …/chapters` | List (by position) / create (appended) |
| `PATCH /api/projects/{pid}/chapters/{cid}` | Rename / status |
| `POST /api/projects/{pid}/chapters/{cid}:archive` | Archive chapter (no hard delete) |
| `GET /api/projects/{pid}/chapters/{cid}/content` | Head revision `{revision_no, source_md, word_count, updated_at}` |
| `PUT /api/projects/{pid}/chapters/{cid}/content` `{source_md, expected_head_no}` | Save → 201 new revision, or 409 with the current head |
| `GET /api/projects/{pid}/chapters/{cid}/revisions` | Revision metadata list (UI in Phase 02) |
| `POST /api/projects/{pid}/exports` `{format:"markdown"}` | Synchronous Markdown export → `export_run` |
| `GET /api/projects/{pid}/exports/{eid}/file` | Download (Content-Disposition with the sanitized name) |
| `GET /api/activity?project_id=&limit=` | Activity feed |

5. Markdown export format (deterministic): YAML front matter (`title`, `subtitle`, `lang`, `pbs_export: {project_id, export_id, schema: "pbs-md-export/1"}`), then for each non-archived chapter in position order `# {title} {#ch-<slug>}` + blank line + `source_md` verbatim + a trailing newline. The file goes to `exports/<eid>/<sanitized-title>.md`, and its sha256 is recorded.

### Step 2: Frontend skeleton (`apps/studio-ui`)
1. `pnpm create vite` (react-ts), TypeScript strict, ESLint flat config + `jsx-a11y` + Prettier, Vitest + RTL + user-event + vitest-axe.
2. Dependencies: `react`, `react-dom`, `react-router`, `@tanstack/react-query`, `react-aria-components`, `openapi-fetch`. Dev: `openapi-typescript`, `@playwright/test` (root `e2e/`).
3. `vite.config.ts`: dev server on `localhost:5173`. Proxy `/api` → `http://127.0.0.1:8765`. The proxy `configure` hook reads `<PBS_WORKSPACE>/runtime/session.token` **per request** (so a Core restart works) and sets `X-PBS-Token`. The UI never sees the token. A CSP meta header in dev.
4. Structure: `src/app/` (router, QueryClient, ErrorBoundary, AppShell), `src/components/` (NavRail, PrivacyBadge, PageHeader, EmptyState, ErrorState, ConfirmDialog, LiveAnnouncer, NotAvailable), `src/features/library/` (LibraryPage, ProjectCard, ProjectFilters, NewProjectForm), `src/features/project/` (ProjectPage: metadata edit + chapter list), `src/features/editor/` (ChapterEditorPage: labeled `<textarea>`, word count, Save button + Ctrl/Cmd+S, unsaved-changes guard, 409 conflict dialog showing "your version vs saved version"), `src/features/activity/`, `src/features/help/` (static help + capabilities table), `src/api/` (generated `schema.d.ts` + typed client), `src/styles/` (tokens: color, spacing, type scale; light/dark with `prefers-color-scheme`; `prefers-reduced-motion`).
5. Navigation: Library ✔, New Book ✔ (create form), Manuscripts ✔ (projects → chapters → editor), Activity ✔, Help ✔. Research / Knowledge / Publishing / AI Settings render `<NotAvailable phase="05|04|07|03">` with `aria-disabled` nav items marked "(Phase NN)". Exports live on ProjectPage ("Export Markdown").
6. Design: original visual language (no borrowed trade dress). Readable serif for manuscript text (bundled OFL font, e.g. Source Serif 4, served locally) and a sans UI font. WCAG AA contrast tokens.

### Step 3: Scripts and docs
- `scripts/setup.ps1` / `setup.sh`: check versions (uv, Node ≥22, pnpm), `uv sync`, `pnpm install`, Playwright browser check.
- `scripts/dev.ps1` / `dev.sh`: start Core and UI (two processes, prefixed logs), fail clearly if a port is busy.
- `scripts/test.ps1` / `test.sh`: ruff, mypy, pytest, eslint, tsc, vitest, build, playwright.
- `scripts/gen-api.ps1`: export OpenAPI from the app factory (no server needed), then run `openapi-typescript`.
- `scripts/seed-demo.py`: creates demo projects **only when run explicitly** and tags them `demo`.
- `README.md`: prerequisites, exact Windows (PowerShell) and macOS (zsh) commands, troubleshooting (Store `python3` alias, Git Bash `link.exe` shadowing, port in use, token file missing, resetting the dev workspace).

### Step 4: Tests (must all pass, with results pasted here)
- Backend unit: `safe_join`/`sanitize_filename` table tests (T-S4), redaction (T-S5), ULID monotonicity, word count, bookmd-0.1 lossless (`unsupported` preserves spans), project validation.
- Backend integration: guard (T-S1, T-S2), bind address (T-S3), project CRUD + search/sort, archive/duplicate (T-P5), isolation (T-P4), save/409 (T-P2, T-P3), immutability trigger, restart persistence (T-P1, new app instance on the same workspace), migrations (T-P7), Markdown export golden (T-P6), socket guard active for the whole suite.
- Frontend: component tests for NewProjectForm validation, LibraryPage empty/error/list states, editor unsaved-guard + conflict dialog, NotAvailable panel. vitest-axe on each page.
- E2E (Playwright, `e2e/vertical-slice.spec.ts`): global setup spawns Core with a temp workspace + Vite. The spec runs the vertical slice **including a real Core process restart** (helper kills and respawns Core on the same workspace) and asserts the downloaded Markdown content. A keyboard-only variant. axe scan.
- `E2E-GOLDEN-01`: steps 1–3 and 11 (MD) pass. Remaining steps are `xfail(Phase NN)`.

### Step 5: Phase exit
Run `scripts/test.ps1`, paste the summaries, update this file (done / limitations / Phase 02 handoff), commit on `phase/01-scaffold`, **STOP**.

### Phase 01 task order (dependency-sorted)
1. Bootstrap (Step 0) → 2. Core config, paths, DB, migration baseline + tests → 3. Security guard, token, redaction + tests → 4. Domain + services + API + tests → 5. OpenAPI → TS client generation → 6. UI shell, nav, tokens, error boundary → 7. Library + New Book + Project pages → 8. Editor + save/conflict → 9. Export + Activity + Help/capabilities → 10. Playwright vertical slice incl. restart → 11. Scripts + README → 12. Full test run, BUILD_STATE update, commit.

---

## Phase log

### Phase 00: Planning (2026-11-22)
- Inspected the repo (empty except the prompt pack) and the environment (see snapshot).
- Created the 8 planning docs + `.gitignore` + `.gitattributes`. Initialized git, added the `origin` remote, and committed and pushed to `main` at the user's request.
- No code. No tests run (none exist).
