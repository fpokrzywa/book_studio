# Personal Book Studio — Test Plan

Status: Draft v0.1 (Phase 00). Principle: **report real results only.** A test that didn't run is reported as "not run", and a validator that is missing is reported as "unavailable".

## 1. Test layers

| Layer | Tooling | Scope | Runs |
|---|---|---|---|
| Unit (backend) | pytest, hypothesis | Domain logic, state machines, `safe_join`, redaction, BookMD parser, BDM invariants, ID reconciliation, price math | Every commit |
| Integration (backend) | pytest + FastAPI `TestClient`/httpx ASGI + temp workspace | API endpoints with a real SQLite file, migrations, job runner, import/export, backup/restore | Every commit |
| Fidelity suite | pytest + checked-in fixtures + golden files | Round trips: BookMD ⇄ BDM ⇄ HTML/MD/EPUB/DOCX/PDF | Every commit touching `document/` or `export/`; nightly full run |
| Contract | `openapi-typescript` diff check | Generated TS client matches the OpenAPI doc | Every commit |
| Unit/component (frontend) | Vitest + React Testing Library + user-event + vitest-axe | Components, forms, error and empty states, a11y rules | Every commit |
| E2E | Playwright (Chromium; WebKit for the macOS proxy later) | Real browser against real Core on a temp workspace, including restart | Every commit (smoke), full on PR |
| Security | pytest + fixtures | Guard middleware, traversal, zip bombs, XXE, XSS, prompt injection, egress, canary-key scans | Every commit |
| Migration | pytest | Each fixture DB → head, then invariants | Every migration change + nightly |
| Performance (Phase 09) | pytest-benchmark + scripted Playwright timings | 100 chapters / 500 assets / 10k chunks | Manual + nightly; numbers recorded, not invented |
| Static | ruff, mypy, ESLint, tsc `--noEmit`, import-linter, license gate, gitleaks | | Every commit |

## 2. Test environment rules

1. **Hermetic workspace.** Every test gets `tmp_path` as `PBS_WORKSPACE`. No test touches the user's real data folder.
2. **Network guard.** A session-wide pytest fixture blocks non-loopback sockets. Tests that need live providers are marked `@pytest.mark.live_cloud` and are skipped unless `PBS_LIVE_TESTS=1`. Ollama tests (`@pytest.mark.ollama`) run only if `OLLAMA_HOST` responds.
3. **Deterministic AI.** The `mock` provider returns fixture-driven outputs keyed by `(task, prompt_template_id, input_hash)`, with optional injected failures (timeout, 429, malformed JSON) and controllable latency so cancel and resume can be tested.
4. **Clock and IDs** are injectable (`Clock`, `IdFactory`) so golden outputs are stable.
5. **Optional tools.** Tests that need Pandoc, WeasyPrint, EPUBCheck or Calibre are marked and **skip with an explicit reason**. CI reports skipped counts. The E2E scenario asserts that the UI shows "unavailable" when a tool is missing.
6. **Fixtures are synthetic or public-domain** (public repo). Each fixture has a `fixtures/README.md` entry describing its source and license.

## 3. Fixture catalog (checked into `fixtures/`)

| Fixture | Contents | Used by |
|---|---|---|
| `bookmd/kitchen-sink.md` | Every BookMD construct: H1–H6 with IDs, nested lists, task list, quote, GFM table with caption + alignment, fenced code (Python, with tabs and trailing spaces), inline + display math, footnotes, citations with locators, figure with alt ≠ caption, callout div, link schemes incl. a `javascript:` link that must be neutralized | Parser, renderers, fidelity |
| `bookmd/unicode.md` | RTL text, combining marks, emoji, CJK, NBSP, smart quotes | Parser, EPUB, PDF fonts |
| `books/three-chapter/` | 3 chapters + 2 images + bibliography (CSL-JSON) + front matter | Export, acceptance scenario |
| `import/sample.docx` | Headings, table, image + caption, footnote, equation (OMML), code style | DOCX import |
| `import/sample.html` | Valid structure + `<script>`, `onerror=`, `<iframe>`, `javascript:` link | HTML import / XSS |
| `import/text.pdf`, `import/scanned.pdf`, `import/encrypted.pdf` | Text PDF, image-only PDF, password-protected PDF | PDF import + warnings |
| `malicious/zipbomb.docx`, `malicious/traversal.zip`, `malicious/xxe.docx` | Archive and XML attacks | Security |
| `malicious/injection-source.md` | "Ignore previous instructions…", fake `</pbs:data>` envelope close, fake citations, a request to exfiltrate | Prompt-injection |
| `mock-ai/*.json` | Deterministic outputs for outline, draft, revise, review | Jobs, scenario |
| `db/rev_<id>.db` | Synthetic DB at each released schema head | Migration |

**As built (Phase 02):** `fixtures/generate.py` writes the binary and HTML fixtures deterministically. They are synthetic, created for this project. The set: `bookmd/kitchen-sink.md`, `import/multi-chapter.{html,md}`, `import/sample.docx` (with an injected Word equation), `import/{text,scanned,encrypted}.pdf`, `malicious/{legacy.doc, zipbomb.docx, traversal.docx, xxe.docx, injection.html}`, `images/engine.png`. Regenerate them with the Core venv: `apps/studio-core/.venv/Scripts/python.exe fixtures/generate.py`.

## 4. Key test cases by area

### 4.1 Persistence and isolation (Phase 01)
- T-P1 Create project → restart Core (new process on the same workspace) → project present with all metadata.
- T-P2 Chapter save creates revision 1, 2, … with content hashes. Revisions are immutable (direct SQL UPDATE raises).
- T-P3 Optimistic concurrency: a save with a stale `expected_head_no` returns 409 and creates no revision.
- T-P4 Isolation: project A's API calls cannot read or modify project B's chapters (404, not 403, to avoid ID probing). A composite-FK violation at the DB level is rejected.
- T-P5 Archive hides the project from the default library view and keeps its data. Duplicate creates a new ID with copied heads.
- T-P6 Markdown export of a project equals the concatenation of head revisions (golden file), with a sanitized filename.
- T-P7 Migrations: empty → head. Head → head is a no-op. A pre-migration snapshot is created when the DB is older. Opening a DB with a newer revision is refused.

### 4.2 Security guards (Phase 01+)
- T-S1 Request without `X-PBS-Token` → 401. Wrong token → 401. Constant-time compare.
- T-S2 `Host: evil.example` → rejected. `Origin: https://evil.example` on POST → 403.
- T-S3 The server socket is bound to 127.0.0.1 (assert the bind address; attempt a connect via a non-loopback interface where available).
- T-S4 `safe_join` table test: `..\\x`, `C:\\x`, `\\\\server\\share`, `a:b`, `CON`, `nul.txt`, `x. `, symlink/junction escape → all rejected.
- T-S5 Log redaction: planted `sk-test-CANARY…` in an exception message → absent from log files.

### 4.3 Document fidelity (Phase 01 minimal, Phase 02 full)
- T-D1 Property test (hypothesis-generated BookMD from a grammar): `parse ∘ serialize ∘ parse ≡ parse`.
- T-D2 Code and math byte-exactness through all text formats.
- T-D3 Figure alt and caption stay distinct in HTML (`alt=` vs `<figcaption>`), EPUB and DOCX.
- T-D4 Unsupported constructs produce `unsupported` blocks + warnings. Never dropped.
- T-D5 Block-ID reconciliation: edit one paragraph in a 50-block chapter → 49 IDs unchanged. Reorder sections → IDs preserved. Explicit `{#id}` always wins.
- T-D6 Chapter reorder keeps asset, citation and annotation references intact (Phase 02).

### 4.4 Jobs and AI (Phase 03)
- T-J1 Kill Core mid-job (subprocess SIGTERM/`TerminateProcess`) → restart → job resumes or goes to `interrupted`. The final proposal exists exactly once.
- T-J2 Cancel during streaming → `cancelled`. No proposal is applicable. Partial output is retained for inspection.
- T-J3 Retry after a 429 uses backoff. `max_attempts` is respected.
- T-J4 Accepting a stale proposal → 409 → rebase flow.
- T-J5 Locked/approved chapter → proposal creation is blocked.
- T-J6 **Local-only zero egress**: the full scenario runs under the socket guard with zero non-loopback attempts. Selecting a cloud provider in local-only → `EgressBlocked`, no fallback.
- T-J7 Cost: no price row → cost `null` and the UI shows "unknown". Estimates are flagged `is_estimate`.

**As built (Phase 03):**

| Case | Tests |
|---|---|
| T-J1 | `test_process_restart.py::test_ai_job_survives_hard_kill_without_double_apply`, `test_ai_jobs.py::test_restart_recovers_running_jobs_without_double_commit`, Playwright `ai.spec.ts` (crash mid-stream) |
| T-J2 | `test_cancel_while_streaming_applies_nothing`, Playwright |
| T-J3 | `test_rate_limit_is_retried_with_backoff`, `test_auth_error_fails_without_retry_then_manual_retry` |
| T-J4 | `test_replace_selection_goes_stale_when_passage_changes`. The "rebase" is to ask again |
| T-J5 | `test_approved_chapter_blocks_requests_and_accepts` |
| T-J6 | `test_local_only_mode_makes_zero_external_calls`, golden step 15, and the session socket guard |
| T-J7 | `test_cloud_needs_confirmation_and_project_consent` (unknown, then priced) |

Adapter contract tests (`test_ai_providers.py`) use recorded wire formats over `httpx2.MockTransport`. The Ollama smoke test (`-m ollama`) runs only when Ollama answers. Cloud checks: `python -m pbs_core.live_check`.

### 4.5 Later phases (summary; detailed in each phase's BUILD_STATE handoff)
- Knowledge: dedupe by hash. A disabled source is never retrieved. Injection fixture causes no state change. Citations resolve only to ledger entries.
- Planning: unsupported market metrics are never produced (assert the schema has no such fields unless a licensed source is configured). An outline change preserves prose.
- Writing: 3-chapter generation with stop/resume. Locked content is untouched. Repeated-paragraph detector finds a planted duplicate.
- Publishing: PDF page size/count via pypdf. EPUB OPF/nav/spine checks. DOCX style and paragraph inspection. The print cover recalculates the spine when the page count changes. EPUBCheck "unavailable" when Java is missing.

## 5. End-to-end acceptance scenario (the "golden path")

**ID:** `E2E-GOLDEN-01`. Automated in Playwright (`e2e/golden-path.spec.ts`) plus a backend driver (`tests/acceptance/test_golden_path.py`) for steps without UI yet. It is extended phase by phase. Each step lists the phase in which it becomes executable. Until then, the step is `xfail(reason="Phase NN")`, **never silently skipped**.

Preconditions: fresh temp workspace, privacy mode `local_only`, mock AI provider configured as "local (test)", Pandoc / WeasyPrint / EPUBCheck present on the "full" CI runner and absent on the "minimal" runner.

| # | Step (user action) | Expected result / assertion | Phase |
|---|---|---|---|
| 1 | Launch the app. Library is empty | Empty state with "New book" CTA. Privacy badge shows **Local-only** | 01 |
| 2 | Create project "The Quiet Engine", type technical, lang `en`, audience "hobbyist engineers", target 30,000 words, formats ebook + paperback | Project card appears. Activity: "Project created". Row persisted | 01 |
| 3 | Restart Core and reload the UI | Project and metadata unchanged | 01 |
| 4 | Ingest sources: import `fixtures/import/sample.docx` as a manuscript and `fixtures/books/three-chapter/sources/*.md` into the knowledge library | Originals stored with sha256. Import preview shows detected chapters; user confirms. Import report lists any losses. Sources indexed (FTS hit on a known phrase). Injection fixture imported without effect | 02 (manuscript), 04 (knowledge) |
| 5 | Create a book brief and generate an outline with the mock provider | Outline proposal with stable node IDs. User edits one node and approves. Chapter skeleton created (`planned`) | 05 |
| 6 | Generate Chapter 2 draft (single chapter mode) | Job runs through stages. Pre-run estimate labeled "estimate". A proposal appears in the review pane with **AI suggestion** badges and source links / **Unverified** flags. No revision until accept | 03 (generic draft), 06 (sectioned + grounded) |
| 7 | Accept the proposal | Revision 2 created, `origin=ai_generated`, linked to job and proposal. Badges are visible per block | 03 |
| 8 | Human edit: rewrite one paragraph, add a table with caption, a display equation and a figure with alt text; save | Revision 3, `origin=human`. The edited block becomes `ai_assisted`. Untouched AI blocks keep `ai_generated`. Block IDs of untouched blocks unchanged | 02 |
| 9 | Restore revision 2 | Revision 4 created (`origin=restored`, `restored_from=rev2`). Revisions 1–3 still listed. Diff 3↔4 shows the removed table | 02 |
| 10 | Restore revision 3 again (re-apply the edits) | Revision 5 = content of 3 | 02 |
| 11 | Export **EPUB**, **DOCX**, **PDF** (plus MD and HTML) | Export runs complete. Files exist under `exports/<id>/` | MD 01; HTML 02; EPUB/DOCX/PDF 07 |
| 12 | Validate | `preflight.json`: PDF trim size equals the selected trim (±0.5 pt), page count > 0, fonts embedded; EPUB has `mimetype` first, valid OPF, nav, spine order = chapter order, alt text present, MathML/SVG present; DOCX contains Heading 1/2 styles, the table, the image, the footnote; EPUBCheck = pass on the full runner and **unavailable** on the minimal runner (never "pass") | 07 |
| 13 | Package | KDP handoff folder: exports, covers (ebook + print wrap computed from the final page count), `metadata.json`, keywords (≤7, editable), disclosure checklist reflecting ≥1 AI-generated chapter, sources list, license notes, `MANUAL_KDP_STEPS.md`. **No network call made.** Secret canary absent from every file | 07 |
| 14 | Backup project → restore as new project | Restored manuscript, metadata, revisions, assets and citations are equivalent (structural compare). The original project is untouched | 02 |
| 15 | Global assertion | Socket guard recorded zero non-loopback connections for the whole run | 03+ |

## 6. Phase exit evidence

Every phase's BUILD_STATE update must paste:
1. The exact commands run.
2. Summary lines from pytest, Vitest and Playwright (pass/fail/skip counts) and the lint/type/build results.
3. The `E2E-GOLDEN-01` status table (steps passing / xfail-by-phase / failing).
4. Skips with reasons (missing tools).
