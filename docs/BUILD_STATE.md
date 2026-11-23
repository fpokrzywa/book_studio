# Personal Book Studio — Build State

> Single source of truth for "where are we". Every phase ends by updating this file with **evidence** (commands + real results).

## Current status

| Field | Value |
|---|---|
| Current phase | **11: Final acceptance testing and stabilisation: COMPLETE (pending user review). Verdict: READY FOR PERSONAL USE, with conditions (docs/FINAL_ACCEPTANCE_REPORT.md)** |
| Previous phases | 10 (Ubuntu deployment and operations), 09 (web architecture) and 08 (advanced features): complete, pending user review; their decisions (P8-1 to P8-12, P9-1 to P9-13, P10-1 to P10-10) are not signed off yet |
| Next phase | Not defined. Do not start one automatically |
| Branch | Working tree on `phase/08-advanced`, stacked on `phase/07-publishing` (PR #7), then Phases 06 to 01. **Phases 08, 09, 10 and 11 are not committed.** A snapshot of the Phase 08 tree alone was saved as git tree object `85170bfbbcc381a4ef2a8156741d73cf11e43d25`, so the two phases can still be committed separately |
| Schema | Alembic head `0010` (`0010_web`, adds tables only). Workspaces migrate automatically, with a snapshot |
| Deployment | `local` (development, loopback only) or `server` (Docker Compose behind Caddy; `docs/DEPLOYMENT.md`) |
| KDP rule set | `kdp-paperback-2026-11-22` (unchanged) |
| OpenAI audio facts | read 2026-11-23 (ADR-0009); OWASP scrypt parameters read 2026-11-23 (ADR-0010) |
| Platforms verified | Windows 11 x64; the Linux image under Docker Desktop's Linux engine. A real Ubuntu host and macOS are **not executed** |
| Last updated | 2026-11-23 (Phase 11) |

## Phase 11 evidence (real results, 2026-11-23): final acceptance and stabilisation

**Verdict: READY FOR PERSONAL USE, with conditions**: run EPUBCheck before submitting an EPUB to a store;
run DEPLOYMENT_VERIFICATION §3 once on a real Ubuntu server; commit the work. Full report:
`docs/FINAL_ACCEPTANCE_REPORT.md`.

Final check: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1` → **exit 0, "All checks passed."**

| Check | Result |
|---|---|
| ruff lint / format | All checks passed / 194 files already formatted |
| mypy `--strict` (153 source files) | Success: no issues found |
| import-linter | 4 kept, 0 broken |
| pytest (Core) | **308 passed, 1 skipped** (the skip is the live Ollama test) |
| License gate | passed: 101 runtime dependencies |
| ESLint + Prettier, TypeScript strict, Vite build | clean, built |
| Vitest + axe | **51 passed** |
| Playwright + axe | **19 passed** |
| Note | The run before this one stopped with one setup error, Windows `WinError 10055` (no socket buffer space), late in pytest. Measured: the test process keeps about 2 open sockets throughout (no leak), so this is the machine running short under load. It happened in 2 of the last 7 full runs. Recorded in KNOWN_ISSUES |

| Area | Evidence |
|---|---|
| Audit | `docs/FEATURE_MATRIX.md`: 100 rows (70 PASS, 26 PARTIAL, 3 BLOCKED, 1 NOT IMPLEMENTED), each tied to tests; UI presence never counted |
| Publishing simulation | `tests/test_final_acceptance.py`: Markdown manuscript imported (original SHA-256 identical); AI suggestion rejected (text byte-identical) and approved (one revision, double accept refused, code and math untouched); DOCX, EPUB and PDF inspected per format (chapters, matter, images, references, tables, code verbatim, math, no duplicates, approved edit present). Results per format in FINAL_ACCEPTANCE_REPORT |
| Ubuntu deployment | DEPLOYMENT_VERIFICATION §2: compose valid; restart policy after a stop and start; migrations; exposure (only NPM listens; Core and Ollama unreachable from the host; backend network internal); logs (0 tracebacks, 0 secrets); end-to-end with `qwen2.5:0.5b` (all PASS, including originals byte for byte); worker killed mid-job → attempt 2 succeeded, 1 suggestion, chapter unchanged; **backup restored into an isolated Compose project with identical fingerprints** (18 revisions, 4 assets, 4 originals); three updates and a rollback |
| Performance (NFR-4, first measurement) | 100 chapters, 500 images, 10,000 chunks: library 85 ms, chapter tree 46 ms, full-text search 41 ms (median of repeated calls), EPUB export 2.7 s (193 KB). API timings on the Windows dev machine; editor keystroke latency not measured |
| Not verified | EPUBCheck (download refused by the session's permission settings), a physical Ubuntu server, Let's Encrypt, cloud providers with real keys, real speech engines, macOS (KNOWN_ISSUES 1 to 6) |

## Phase 11: what changed

No features were added and the architecture is unchanged.

- **Fixes:**
  - `backup.sh --path-file`, with `update.sh` and `run_e2e.sh` no longer using `tee /dev/stderr`;
  - `restore.sh` restores into an empty folder (new server);
  - `PBS_PROJECT_NAME` for isolated copies;
  - `run_e2e.sh` checks originals byte for byte and warns not to use the studio while it runs;
  - e2e helpers `openAiPanel` and `addMockProvider` remove two test races.
- **Tests:** `test_final_acceptance.py`.
- **Documents:** `FINAL_ACCEPTANCE_REPORT.md`, `FEATURE_MATRIX.md`, `DEPLOYMENT_VERIFICATION.md`,
  `KNOWN_ISSUES.md` and `USER_GUIDE.md`; README links them; this file now has the Phase 10 evidence
  that DEPLOYMENT.md cited.

## Phase 11: bugs found and fixed

- **Log truncation (operations, high):** when `update.sh` or `run_e2e.sh` output was redirected to a file
  (cron), `tee /dev/stderr` reopened that file with truncation, wiping earlier lines and leaving NUL
  bytes. It was found because the harness log came back with NULs. Re-tested on Ubuntu: an appended
  `update.sh` log keeps its first line, with 0 NUL bytes.
- **Flaky browser tests (medium):** one or two different specs failed in each full run.
  - Cause 1: tests checked the AI panel before the editor rendered, then clicked the toggle, closing a
    panel stored as open.
  - Cause 2: tests navigated away before "Add provider" was saved, so no model existed.
  - Both were test races, not app defects. The fix is shared helpers that wait for the real state;
    repeated runs pass.
- **Restore onto a new server (low):** `restore.sh` assumed an existing data folder. Fixed and used for
  the isolated restore.
- **Test-bed only (not shipped):** Docker's overlay storage inside the test container; a stale `dockerd`
  PID file after the box stopped; `/etc/hosts` rewritten on restart; `ss` missing in the minimal image.

## Remaining issues

See `docs/KNOWN_ISSUES.md`: 6 unverified items, 7 medium, 7 low; none critical.

## Next

No further phase is defined. FINAL_ACCEPTANCE_REPORT "Recommended next improvements" lists the
candidates. EPUBCheck and a real-server run come first.

---

## Phase 10 evidence (real results, 2026-11-23)

### Local checks (Windows 11, CPython 3.12.13, Node 26.13)

The first three Phase 10 runs each had one different Playwright failure. Phase 11 traced them to two races in the browser tests (fixed there, see Phase 11). The run below is after those fixes.

Command: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1` → **exit 0, "All checks passed."**

| Check | Result |
|---|---|
| ruff lint / format (Core) | All checks passed / 194 files already formatted |
| mypy `--strict` (153 source files) | Success: no issues found |
| import-linter | 4 kept, 0 broken |
| pytest (Core) | **308 passed, 1 skipped** (11 new in `test_ops.py`; the count also includes Phase 11's `test_final_acceptance.py`). The skip is the live Ollama smoke test |
| License gate | passed: 101 runtime dependencies |
| ESLint + Prettier, TypeScript strict | clean |
| Vitest + RTL + axe-core | **51 passed** |
| Vite production build | built |
| Playwright + axe | **19 passed** |

### Ubuntu deployment (the system the procedure was run on)

Ubuntu 24.04.5 LTS userland with Docker Engine 29.10.0 and Docker Compose v5.8.0, **inside a privileged
container on this Windows machine** (its own `dockerd`, `/var/lib/docker` on a volume). It is not a
physical or cloud server. Nginx Proxy Manager 2.17.1 runs next to the studio, on the shared `npm_proxy`
network, with a custom certificate for `books.test` from a private test CA (stands in for Let's Encrypt).
Ollama 0.40.17 runs in the `ollama` container with `qwen2.5:0.5b` (397 MB), pulled with the documented
one-off command. Every account and admin password was generated on that system and never left it.

| Step | Command | Result |
|---|---|---|
| Install | `install.sh --domain books.test --ollama docker` | `.env`, folders, master key, `npm_proxy` network, image `b534443cd8d3` built, migrated 0 → 0010, app and worker healthy, validation PASSED |
| Proxy host | NPM API (same fields as the UI): `book-studio-app:8765`, custom cert, Force SSL, the four Advanced lines | `https://books.test/healthz` 200; `http://` → 301 to https |
| Validate through NPM | `validate.sh --url https://books.test --cacert ca.pem` | 14 PASS: healthy, check OK, **no host port on app, worker or ollama**, trusted subnet matches, data 10001/700, key 400, `/healthz` via NPM, API 401 without sign-in, HSTS and CSP present |
| End to end | `validation/run_e2e.sh` (below) | **END-TO-END VALIDATION PASSED**: 22 + 5 + 5 + 1 + 6 checks |
| Update | `update.sh` (a new commit) | verified pre-update backup, new image `231b57488191` built next to the old one, migrate "nothing to do", healthy, validation PASSED |
| Rollback | `rollback.sh --yes` | back on `b534443cd8d3` with the pre-update backup; a book written after the update is gone from the studio and kept in `data.pre-restore-…`; validation PASSED |
| Remote Ollama | second Ollama published on the system's own address (stands in for another computer), address added to `PBS_LOCAL_AI_HOSTS` | provider created, connection test OK, model listed; an address not on the list refused (422) |
| Cloud switch | `PBS_ALLOW_CLOUD=false`, `compose up -d` | allowing cloud in the app → 409 `cloud_disabled_by_operator`; status local-only; local model test still OK |
| Monitoring | `status.sh`, `diagnose.sh` | jobs/tasks by status, heartbeat 6 s, content counts, disk; diagnostics 9 sections, 0 secrets found in it |

End-to-end run (`run_e2e.sh --url https://books.test`, the representative manuscript "The Lighthouse
Ledger": three chapters, a section heading, bold and italic, bulleted and numbered lists, a table and
an embedded PNG figure with a caption):

| # | Prompt 10 step | Result |
|---|---|---|
| 9 | Authentication and authorised access | anonymous API 401; wrong password 401; signed in over HTTPS (`deployment: server`); a write without the CSRF token 403 |
| 1 | Import an existing book | DOCX uploaded and parsed (3 chapters), committed as a new book |
| 2 | Chapter structure and assets | titles in order; table, lists and emphasis kept; 1 image asset stored, served as PNG, referenced in its chapter |
| 3 | AI-assisted edit | Ollama connection test OK; model listed; a "revise" job on the first paragraph ran **in the worker** and succeeded |
| 4 | Review and approve | the suggestion waited as pending; the chapter was unchanged until approval; approved |
| 5 | New revision | history `imported → ai_generated → human`; the new revision is the head |
| 6 | Export DOCX, EPUB, PDF | one background task in the worker: DOCX 39,729 bytes, EPUB 81,065 bytes, PDF 38,277 bytes / 7 pages, each downloaded and checked by file signature |
| 7 | Restart the services | `compose restart app worker`: session still valid; chapters, all 5 revision hashes, the asset and the 3 exported files identical |
| 7b | Recreate every container | `compose down` (no `-v`) + `up -d`: identical again |
| 8 | Book, history and assets still exist | as above, after each restart and after the restore |
| 10 | Backup and restore | `backup.sh` (verified: integrity ok, schema 0010, 2 books, 8 revisions, 2 assets); a book created after it; `restore.sh --yes`: the later book is gone (404) and everything recorded before is identical |

Publishing compliance was **not** assessed: the run proves the files are produced, downloadable and of the
right type. The studio's preflight findings are not a store's verdict (Phase 07 limitations apply).

### Prompt 10 acceptance → evidence

| Acceptance item | Evidence |
|---|---|
| Accessible in a browser | Through Nginx Proxy Manager over HTTPS on the Ubuntu system (validate.sh, e2e); the browser UI itself is the one tested by Playwright (19 specs) |
| Completes the original book-publishing workflows | e2e steps 1 to 6: import, structure and assets, AI-assisted edit, approval, revision, DOCX/EPUB/PDF |
| Preserves user data | Identical chapters, revision hashes, assets and exports after a restart, a full container recreation and a restore; data in host folders that no Docker command deletes |
| Safely restarted, updated, backed up and restored on Ubuntu | restart and recreation (e2e), `update.sh`, `rollback.sh`, `backup.sh`, `restore.sh` all run on the Ubuntu system as above; none removes volumes or data folders (checked: no `down -v`, `volume rm` or `rm -rf` in the scripts; restore and rollback move data aside) |

### Deliverables → where

| Deliverable | Where |
|---|---|
| Working Ubuntu deployment | Run as above (on a containerised Ubuntu, not a physical server) |
| Docker Compose configuration | `deploy/compose.yaml`, `deploy/compose.publish.yaml`, `deploy/Dockerfile` |
| Production environment template | `deploy/.env.example` |
| Persistent storage configuration | Bind mounts under `/srv/book-studio` (DEPLOYMENT §6) |
| Installation and update instructions | `docs/DEPLOYMENT.md`, `docs/OPERATIONS.md`, `deploy/scripts/install.sh`, `update.sh` |
| Backup and restore scripts | `deploy/scripts/backup.sh`, `restore.sh`, `rollback.sh` |
| End-to-end test results | This section; `deploy/validation/` |
| README, architecture, BUILD_STATE | README, ARCHITECTURE §1.3, SECURITY §7i, ROADMAP, TEST_PLAN §4.4g, ADR-0011, this file |

## Phase 10: what was built

- **Compose for Nginx Proxy Manager** (`deploy/compose.yaml`):
  - `app` joins the external `npm_proxy` network as `book-studio-app`, with no host port;
  - `worker` has a heartbeat health check;
  - optional `ollama` on an internal-only network;
  - every service has `restart: unless-stopped`, bind-mounted data, a read-only root filesystem, no
    capabilities and log rotation.
  - `compose.publish.yaml` publishes Core on one address when NPM runs on another machine.
  - The Caddy proxy and `make-secret.sh` from Phase 09 are removed.
- **Core** (`ops.py`, `__main__.py`):
  - commands `migrate`, `status [--json]`, `check` and `verify-backup`;
  - `PBS_ALLOW_CLOUD` operator switch (egress gate, privacy endpoint, status, system info);
  - `PBS_LOCAL_AI_HOSTS` accepts IPv4 addresses for a remote Ollama;
  - AI status reports both.
- **UI:** AI settings shows when the operator has turned cloud AI off (the option is disabled with an
  explanation) and lists the private model hosts.
- **Scripts** (`deploy/scripts/`):
  - `common.sh` reads `.env` literally;
  - `install.sh`, `update.sh`, `backup.sh`, `restore.sh`, `rollback.sh`, `validate.sh`, `status.sh`,
    `diagnose.sh`.
- **Validation** (`deploy/validation/`): `make_manuscript.py` (representative DOCX), `e2e_validate.py`
  (standard library only) and `run_e2e.sh`.
- **Docs:** `docs/DEPLOYMENT.md` rewritten for NPM, new `docs/OPERATIONS.md`, ADR-0011; README,
  ARCHITECTURE, SECURITY, ROADMAP and TEST_PLAN updated.

## Decisions taken in Phase 10 (need your validation)

Full text in ADR-0011.

| # | Decision |
|---|---|
| P10-1 | Services `app`, `worker`, optional `ollama`. **No separate frontend server, database, Redis or broker** (Core serves the UI; SQLite holds data and the durable queue) |
| P10-2 | NPM reaches the app over a shared external network as `book-studio-app:8765`; no host port; `compose.publish.yaml` for NPM elsewhere; Caddy removed |
| P10-3 | Trusted proxies = the shared network's subnet, refreshed by `install.sh`, checked by `validate.sh` |
| P10-4 | All data in host folders under `/srv/book-studio` (bind mounts), data 10001/700, key 400 |
| P10-5 | Cold backups (seconds of downtime), verified with the running image, checksum and manifest |
| P10-6 | Restore and rollback never delete: data moved aside; old images kept; rollback = old image + pre-update backup |
| P10-7 | Operations commands live in Core; shell scripts only orchestrate Docker |
| P10-8 | Remote Ollama by IPv4 address or name in `PBS_LOCAL_AI_HOSTS`; host Ollama via `host.docker.internal` |
| P10-9 | `PBS_ALLOW_CLOUD=false` operator switch overrides the in-app setting |
| P10-10 | The end-to-end AI step uses a real small local model (`qwen2.5:0.5b`), not the test model |

## Known limitations (Phase 10, honest list)

1. **The "Ubuntu server" was Ubuntu 24.04.5 in a privileged container** on this Windows machine, with its
   own Docker Engine. A physical or cloud Ubuntu host was not used. Kernel, firewall (`ufw`) and systemd
   behaviour of a real server were not exercised.
2. **Let's Encrypt, DNS challenges and VPN access were not tested.** NPM served a custom certificate from a
   private CA. Devices other than the server itself never connected.
3. **Ollama installed natively on the host** (`host.docker.internal`) was not tested. The "other computer"
   was a second Ollama container published on the same system's address.
4. **Cloud providers were not called with real keys** (no keys used; their adapters keep their offline
   contract tests). The cloud switch was tested only in the refusing direction.
5. **The AI edit's quality was not judged**: a 0.5B model on CPU proves the pipeline, not the writing.
6. **Publishing compliance was not validated** (KDP, other stores). Files are produced and typed correctly;
   EPUBCheck is not in the image.
7. **Backups need a few seconds of downtime** and stay on the same server unless the operator copies them
   off. There is no built-in off-site copy or encryption of backup archives (the provider keys inside are
   encrypted; manuscripts are not).
8. **The Ollama image is not pinned** (`PBS_OLLAMA_TAG=latest` by default) and no image vulnerability scan
   was run.
9. Remote Ollama shows the label "Ollama (local)" and the message "running locally" even on another
   machine (cosmetic; it is treated as a private host).
10. Executable bits: the scripts are mode 755 in this working tree, but Windows Git may not record that.
    When committing, the mode must be set in the index (`git update-index --chmod=+x`), or the docs' `sudo
    deploy/scripts/...` calls need `bash` in front.

## Phase 10: bugs found and fixed

- **Docker-in-Docker overlay failure** in the test system (overlay on overlay): `/var/lib/docker` got its
  own volume. This only affects the test bed, not the deployment.
- **Stale trusted-proxy subnet after the proxy network is recreated**: `install.sh` now re-derives it on
  every run and `validate.sh` fails on a mismatch.
- **`app` was the app's name on a shared proxy network**, which can clash with other stacks: it now has the
  alias `book-studio-app`.
- **One-off `docker compose run` steps swallowed the calling script's standard input** (found when a piped
  script stopped after `update.sh`): they now read from `/dev/null`. `update.sh` also hid the backup's
  progress lines; it now shows them.
- **`validate.sh` could not check HTTPS with a private CA**: added `--cacert`.
- **Backup verification missed data still in SQLite's WAL** and let a raw SQLite error escape: both fixed
  (`test_ops.py`).
- **DEPLOYMENT's first draft listed data folders that do not exist** (`exports/`, `publishing/`): corrected
  from the real layout on the Ubuntu system (`projects/<book>/publish/`, `originals/sha256/`, `narration/`).

## Phase 11 handoff

Phase 11 is not defined. Preserve: no destructive commands in scripts; data only in host folders; verified
backups; rollback = old image + pre-update backup; deny-by-default sign-in and CSRF; the operator's cloud
switch. Candidates:
- run the same procedure on a real Ubuntu server, with Let's Encrypt (DNS challenge) and a VPN;
- off-site, encrypted backups;
- an image vulnerability scan and a pinned Ollama tag;
- imports as background tasks (Phase 09 limitation 2);
- Phase 08 data in per-book backups;
- the open desktop-era gates (feature matrix, performance numbers, release checklist).

---

## Phase 09 evidence (real results, 2026-11-23, Windows 11, CPython 3.12.13, Node 26.13, Docker 29.9.2)

Command: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1` → **exit 0, "All checks passed."**

| Check | Result |
|---|---|
| ruff lint / format (Core) | All checks passed / 191 files already formatted |
| mypy `--strict` (152 source files) | Success: no issues found |
| import-linter | 4 kept, 0 broken |
| pytest (Core) | **296 passed, 1 skipped** (26 new in `test_web.py`, 1 new real-process test; existing tests now sign in). The skip is the Ollama smoke test (no local Ollama) |
| License gate | passed: 101 runtime dependencies (`cryptography` is now direct; `cffi`, `pycparser` with it) |
| ESLint (jsx-a11y strict) + Prettier, TypeScript strict | clean |
| Vitest + RTL + axe-core | **51 passed** (new `Auth.test.tsx`, 5 tests) |
| Vite production build | built |
| Playwright + axe (WCAG 2.2 AA tags) | **19 passed** (new `web.spec.ts`; every earlier spec now runs signed in) |
| Migrations | head `0010`; fresh → head, upgrade from 0001 preserving content, models ≡ migrations |

Docker (manual run, recorded here; not part of `test.ps1`): `docker compose -f deploy/compose.yaml build` built
`personal-book-studio:local` (557 MB). The full stack (proxy, app, worker) was started under Docker Desktop's
Linux engine with a throwaway key and the name `books.localhost`, then checked over HTTPS with `curl`:

| Step | Result |
|---|---|
| `/healthz` and `/` through Caddy (`tls internal`) | 200; the UI's `index.html` with the CSP, HSTS and `X-Frame-Options: DENY` headers |
| `GET /api/projects` without signing in | 401 |
| Setup code read with `docker compose exec app cat /data/runtime/setup-code.txt`; setup | signed in; cookie `__Host-pbs_session` (Secure); `deployment: server` |
| Create a book and chapter, save text | 200 |
| The same write without `X-PBS-CSRF` | 403 |
| `POST .../publishing/build-task` for EPUB and PDF | the **worker** container built both (`succeeded`); `worker_running: true`; schema `0010` |
| Store an OpenAI key (canary) | store `encrypted-file`, secure; the canary is in none of `secrets.enc.json`, `studio.db`, `core.jsonl` |
| Setup code in container or file logs | 0 occurrences |
| `docker compose restart app worker`, then read with the same cookie | revision 1 and the exact text; the session survived |
| `http://127.0.0.1:8765` from the host | no answer (Core has no published port) |

The stack and its volumes were removed afterwards and the throwaway key deleted. **It has not been run on a real
Ubuntu host.**

Existing data: a copy of the dev workspace (4 books, 6 chapters, 6 revisions, 1 series, 5 canon entities) was opened
by the new Core: schema 0009 → 0010 with a snapshot (`db-backups/studio-0009-….db`); a hash of every row in
`project`, `chapter`, `chapter_revision`, `series`, `canon_entity` and `translation_edition` is identical before and
after.

### Prompt 09 acceptance → evidence

| Acceptance item | Where it is proven |
|---|---|
| Application runs through a standard web browser | It always did: no Tauri or Electron code existed (ADR-0010 §2). Core now also serves the built UI itself (`PBS_UI_DIST`; `test_built_ui_is_served_without_exposing_other_files`; the Docker run above). Playwright drives Chromium against Core through the whole suite |
| No desktop application is required | Nothing desktop remains: the per-launch token, the Vite token injection and the loopback-only rule for servers are gone; `local` deployment still refuses non-loopback binds. The desktop packaging plan is retired (ADR-0010, ROADMAP) |
| Features from Phases 01 to 08 remain functional | The whole existing suite passes behind sign-in (pytest, Vitest, every Playwright spec including Phase 08's acceptance) — see the table above. `test_existing_content_survives_and_phase08_routes_work_when_signed_in` |
| Authentication and file security tests pass | `test_web.py` (26 tests): every one of the 219 API operations needs a session; every write needs the CSRF token; setup code; throttling; cookie flags; logout, password change and reset end sessions; idle and absolute expiry; security headers; oversized and streamed bodies; server-mode cookie and HSTS; built-UI and file-endpoint traversal probes; content-typed uploads; encrypted key store. `test_security.py` (guard). `Auth.test.tsx`, `e2e/web.spec.ts` |
| Existing book data and revisions remain intact | Migration `0010` only adds tables; `test_migrations.py` (fresh, upgrade from 0001 preserving content, models ≡ migrations); the dev-workspace copy above; `test_content_survives_hard_kill_and_restart` |
| Structurally ready for Ubuntu Docker deployment | `deploy/Dockerfile`, `deploy/compose.yaml`, `deploy/Caddyfile`, `deploy/.env.example`, `deploy/make-secret.sh`, `.dockerignore`, `docs/DEPLOYMENT.md`; built and run under Docker as above |

### Other Phase 09 requirements → evidence

| Requirement | Evidence |
|---|---|
| Inspect and document findings and migration decisions | `docs/ADR/0010-web-deployment.md` §2 (findings) and §4 (P9-1 to P9-13) |
| Durable worker jobs for generation, AI, imports, exports | AI and generation jobs already ran in the durable runner; it now runs in a separate `worker` process (`test_separate_web_and_worker_processes`: the web process only queues; the worker runs a queued AI job and an EPUB build; a second worker refuses to start). Publishing builds, covers, packages and audio export are durable tasks (`test_publishing_build_runs_as_a_durable_task`, crash recovery, failure kept). **Imports remain synchronous** (P9-10, limitation 2) |
| Persistent server-side storage | One `/data` volume, unchanged workspace layout (DEPLOYMENT §1) |
| All existing local and cloud providers | Unchanged adapters and egress gate; `PBS_LOCAL_AI_HOSTS` adds private hosts (`test_configured_private_model_host_is_local_and_nothing_else_is`) |
| Replace desktop file system calls and dialogs | None existed: uploads and downloads were already HTTP (ADR-0010 §2) |
| Secure handling of API keys | `test_encrypted_key_store_keeps_no_plaintext_and_fails_closed`, `test_server_without_key_file_never_falls_back_to_a_desktop_keyring`, the Docker canary check |
| Upload type and size validation; path traversal | `test_oversized_request_is_refused_before_it_is_read`, `test_streamed_body_over_the_limit_is_cut_off`, `test_uploads_check_type_by_content_not_name`, `test_file_endpoints_refuse_path_tricks`, plus the Phase 02 archive and import tests |
| Safe processing of untrusted documents | Unchanged Phase 02/04 controls (defusedxml, archive limits, nh3, no raw HTML), still passing |
| CSRF, CORS, security headers | `test_every_state_changing_route_requires_the_session_csrf_token`, `test_security_headers_on_every_response`, `test_allowed_origin_works_and_no_cors_headers`, `test_preflight_gets_no_cors_approval` |
| Private-by-default network; nothing exposed | Compose: only the proxy publishes, on 127.0.0.1 by default; Ollama on an internal network; Core unreachable from the host in the Docker run |
| Background job persistence and recovery | `test_ai_job_survives_hard_kill_without_double_apply` (real process kill), `test_task_left_running_by_a_crash_is_retried_then_interrupted` |
| Manuscripts and revisions survive restarts | `test_content_survives_hard_kill_and_restart` (now also: the session survives; signed-out stays signed out), `e2e/web.spec.ts`, the Docker restart |
| Local-only AI with cloud disabled | Existing `test_golden_path` and Phase 08 local-only tests still pass; egress unchanged |
| Browser functionality without a desktop runtime | Every Playwright spec; `e2e/web.spec.ts` covers setup, sign-in, sign-out, restart |

## Phase 09: what was built

- **Accounts and sessions** (`services/auth.py`, `security/passwords.py`, `api/routes_auth.py`, tables `user_account` and `auth_session`): first-run setup with a one-time code; sign-in, sign-out, password change, "sign out other browsers"; command-line `create-user` and `reset-password`.
- **Request guard** (`security/guard.py`, replacing the loopback token guard): Host and Origin checks, deny-by-default session check for `/api`, CSRF token on writes, request-size limit, security headers.
- **Server mode** (`config.py`): `PBS_DEPLOYMENT=server` with `PBS_PUBLIC_ORIGIN`, `PBS_TRUSTED_PROXIES`, `PBS_ROLE` (`all`, `web`, `worker`), `PBS_UI_DIST`, `PBS_LOCAL_AI_HOSTS`, session limits. Local mode keeps the loopback-only rule.
- **Encrypted key store** (`security/secrets.py`, `EncryptedFileStore`) with the master key from a Docker secret; `cryptography` added as a direct dependency (it was already in the lock file as a transitive one).
- **Background worker**: `python -m pbs_core worker`, an exclusive file lock (`storage/locks.py`), a heartbeat shown in the UI; **durable background tasks** (`services/tasks.py`, table `background_task`) for publishing builds, covers, packages and audio export, with `/build-task`, `/covers-task`, `/package-task`, `/narration/export-task` and `GET /api/tasks/{id}`.
- **Core serves the built UI** with SPA fallback and long-lived caching for hashed assets.
- **UI**: sign-in and setup screens (`features/auth/AuthGate.tsx`), Account page, CSRF header on every write, return to sign-in when a session ends, builds and audio export run through the task queue (same buttons, `runTask` polling), a worker-not-running notice on servers, updated Help text and key-store label, styles for untyped and password inputs.
- **Deployment**: `deploy/` (Dockerfile, Compose, Caddyfile, `.env.example`, `make-secret.sh`, `secrets/.gitignore`), `.dockerignore`, `docs/DEPLOYMENT.md`.
- **Docs**: ADR-0010; ARCHITECTURE §1 note, §1.2 and §10; SECURITY §7h; DATA_MODEL §3.11; TEST_PLAN §4.4f; ROADMAP phases 09 and 10; README; ADR-0001 §6 marked superseded.

## Decisions taken in Phase 09 (need your validation)

Full text in ADR-0010 §4.

| # | Decision |
|---|---|
| P9-1 | Browser-first; the Tauri desktop plan is retired. `local` deployment stays for development |
| P9-2 | Keep SQLite; one web process and one worker on one host; volume on a local disk |
| P9-3 | **One account per studio**; authorization is "signed-in owner", enforced deny-by-default for every `/api` route. No multi-user |
| P9-4 | scrypt n=2^17, r=8, p=1; at least 12 characters, no composition rules |
| P9-5 | Session cookie `HttpOnly`, `SameSite=Strict`, `__Host-` + `Secure` on https; hashed tokens; idle 12 h, absolute 14 days (my judgement, configurable) |
| P9-6 | Per-session CSRF token in `X-PBS-CSRF` on every write, plus Origin/Fetch-metadata checks |
| P9-7 | First account via the one-time setup code file, or the server command line |
| P9-8 | AES-256-GCM key store; master key as a Docker secret outside the data volume; fail closed |
| P9-9 | TLS at Caddy; ports published on 127.0.0.1 by default; Core trusts forwarded headers only from the proxy's fixed address |
| P9-10 | Builds, covers, packages and audio export run as durable tasks; imports stay synchronous |
| P9-11 | `PBS_LOCAL_AI_HOSTS` operator allowlist for private model hosts; Ollama on an internal network |
| P9-12 | Sign-in throttling in memory: 5 failures / 15 minutes per address and per username |
| P9-13 | Core serves the built UI with strict headers |

## Known limitations (Phase 09, honest list)

1. **Not run on a real Ubuntu host.** The image and Compose stack were built and run with Docker Desktop's Linux engine on Windows. Caddy's ACME (public certificate) path was not exercised; only `tls internal`.
2. **Imports are still synchronous** (P9-10). A large Word or PDF import runs inside the request; Caddy has no response timeout by default, but a slow import blocks that one request.
3. **One account only.** No multi-user, roles, or per-book sharing.
4. **Sign-in throttling is per process and in memory**; a restart clears it.
5. **Whole-studio backup of the Docker volume is a documented manual command**, not a feature. Per-book backups still omit Phase 08 data (Phase 08 limitation 6) and, by design, accounts and sessions.
6. **No automated vulnerability scan of the image** (for example Trivy or Docker Scout) was run, and the `ollama/ollama` image is not pinned to a version.
7. The original Phase 09 gates written for the desktop plan (feature matrix, performance on the 100-chapter fixture, release checklist) were not part of this redefined phase and are **not done**.
8. The visual check created a throwaway workspace (deleted afterwards). Your `.pbs-data` was not opened by the new Core, so on your next `scripts/dev.ps1` it migrates to 0010 (with a snapshot) and asks you to create the account with the setup code.

## Phase 09: bugs found and fixed

- **The Compose proxy's fixed address collided** first with another project's Docker network on this machine and then with the address Docker gave the app container. The subnet, the automatic range and the proxy address are now configurable, with the proxy outside the automatic range by default.
- **Password and untyped inputs had no field styling** (visual check of the sign-in pages); the global input rule now covers them, which also improves untyped inputs on earlier pages.
- **The Account page's form had no spacing and its buttons stretched** (visual check). Fixed with a scoped form style.
- **The new sign-in test fixture ran Windows out of socket buffers** (WinError 10055) in a full run: it signed in before entering the TestClient, so each request started its own event loop. Clients are now entered first, then signed in.
- **The first route-enumeration test found no routes**: this FastAPI version wraps included routers, so the test now reads the OpenAPI schema (219 operations).

## Phase 10 handoff

Phase 10 is not defined yet (the desktop plan is retired). Preserve: deny-by-default sign-in, CSRF on writes, hashed
sessions, the encrypted key store and the one-worker lock. Candidates:
- run the stack on a real Ubuntu LTS host, including a public ACME certificate;
- move imports to the task queue;
- an image vulnerability scan in CI and a pinned Ollama image;
- a scheduled whole-volume backup;
- Phase 08 data in per-book backups;
- the open desktop-era gates (feature matrix, performance numbers, release checklist).

---

## Phase 08 evidence (real results, 2026-11-23, Windows 11, CPython 3.12.13, Node 26.13)

Command: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1` → **exit 0, "All checks passed."**

| Check | Result |
|---|---|
| ruff lint / format (Core) | All checks passed / 182 files already formatted |
| mypy `--strict` (145 source files) | Success: no issues found |
| import-linter | 4 kept, 0 broken |
| pytest (Core) | **268 passed, 1 skipped** (13 new in `test_advanced.py`). The skip is the Ollama smoke test (no local Ollama) |
| License gate | passed: 98 runtime dependencies (no new runtime dependency; audio uses the standard library `wave` module) |
| ESLint (jsx-a11y strict) + Prettier, TypeScript strict | clean (two justified `media-has-caption` exceptions: audio-only players next to their transcript, WCAG 1.2.1) |
| Vitest + RTL + axe-core | **46 passed** (new `Series.test.tsx`, 3 tests) |
| Vite production build | built |
| Playwright + axe (WCAG 2.2 AA tags) | **18 passed** (new `advanced.spec.ts`, 2 tests) |
| Migrations | head `0009`; fresh → head, head → head no-op, models ≡ migrations, upgrade with a snapshot |

### Prompt 08 acceptance → evidence

| Acceptance item | Where it is proven |
|---|---|
| Create two books in a shared fictional series, modify canon, detect an intentional contradiction, and preserve the user's resolution | `test_series_canon_contradiction_and_resolution_survive_rerun`. Two books in "Tides of Salt". Canon "eye colour: grey" is corrected to "green"; the old row is kept with `superseded_by`. Book 2's "Mara's brown eyes" is found (rule `trait`, found value "brown"), with offsets that select exactly that sentence and a link `/projects/{b2}/chapters/{c2}?select=start-end`. The author marks it "intended" with a note; a re-run finds 0 new, and the decision and note are kept. The manuscript is untouched (head revision 1). Then "update canon" makes "brown" canon with provenance pointing at the finding; on the next run the finding is no longer present (its decision kept), and book 1's "green eyes" is now flagged. **Playwright `advanced.spec.ts` does the same in the UI**: create the series, add both books, add Mara and the fact, edit it ("Earlier values (1)"), run the check, see the passage link, resolve "Intended" with a note, re-run (nothing open; the decision shows under "resolved"), open the passage in the editor |
| Translate one chapter without editing the source text; show language-specific chapter links | `test_translate_one_chapter_without_touching_source`. The approved chapter is translated into French with the test model, as a proposal on the French edition's chapter. Source: same head revision, same text, still one revision. Code, `$E = mc^2$`, `[@smith2020]` and `[^1]` are kept byte for byte. Idiom and term-list items are flagged. Accepting the proposal writes revision 1 of the French chapter only. Links: the source chapter lists `fr` → the target chapter (status "accepted"); the target says "translated from" the source chapter, with its link; slug and position match. **Playwright**: create the `fr` edition in the UI, translate with the test model, "Translation waiting for your review", the source text and revision unchanged, the editor's "Other languages" panel links both ways |
| Narration and transcription degrade gracefully if no provider is installed | `test_narration_degrades_gracefully_without_an_engine` (PATH lookups patched to find nothing): engines listed as "Not installed: …"; synthesis refused with `disabled` while off, then `unavailable` once eSpeak is chosen; **the script is still prepared and readable**; export says there is no audio yet. `test_transcription_degrades_gracefully_without_whisper`: 409 `unavailable`, and the recording stays "imported". Playwright: the script is prepared and shown with no engine; "Make audio" explains narration is off |
| No cloud calls in local-only mode | `test_local_only_mode_blocks_cloud_speech_and_transcription`: OpenAI chosen for speech and transcription, key stored, local-only mode → both 409 "Local-only mode is on…"; **the mock transport received 0 requests and `egress.external_requests()` is unchanged**; cloud engines are listed as unavailable. `test_cloud_speech_and_transcription_when_allowed` shows the cloud path needs cloud mode **and** the book's consent (409 with no request before consent) |
| Tests pass, optional dependencies documented, BUILD_STATE updated | This section. README "Series, translations, narration and interviews (Phase 08)" → **Optional tools** table (eSpeak NG, Piper + `PBS_PIPER_MODEL`, openai-whisper + FFmpeg, OpenAI, EPUBCheck) |

### Other Phase 08 requirements → evidence

| Requirement | Evidence |
|---|---|
| Series workspace: series/book relationships, shared story bible, characters (traits, aliases, relationships), location cards, plot threads, chronology and cross-book continuity | Tables in DATA_MODEL §3.10; Series pages (Books, Story bible, Relationships, Continuity review); chronology ordering and warnings in `series.continuity.chronology`; series canon added to drafting prompts (`test_series_canon_reaches_writing_prompts`) |
| Editable structured facts with provenance; author-approved canon distinct from AI suggestions | status and origin on every entity, fact and relationship; book notes import as suggestions; `test_relationship_check_and_suggestions_are_not_canon` (a suggested age is never compared); Vitest `Series.test.tsx` (suggestion vs canon labels, approve) |
| Highlight contradictions with passage links; the user resolves manually | four rules; offsets and links; four resolutions; the editor selects `?select=start-end` on open |
| Relationship visualization if practical; text editing works without it | `RelationshipMap` (SVG ring) beside the text list, which is the accessible version; Vitest checks both. The editor and story bible do not depend on it |
| Pen-name profiles with editable voice rules; show the active voice per project | `PenNameEditor` on Author voice; `ProjectVoicePanel` on the book page; rules in prompts (`test_pen_name_voice_rules_shown_per_project_and_used_in_prompts`) |
| Translation: approved original revision, language and provider; independent linked revisions; preserve chapter IDs, named entities, figures, code/math, citations and structural links; flag idiom and terminology inconsistencies; don't overwrite the original | ADR-0009 §4; `test_translation_requires_an_approved_revision_and_rejects_lost_placeholders` (not approved → 409 `not_approved`; a revision labelled "Approved" counts; a reply dropping a placeholder → `invalid_output`, no proposal; duplicate language, edition of an edition, or the source language refused) |
| Narration: speech-ready chunks, a configured local or cloud provider only when enabled, chapter-to-audio alignment and progress, export with chapter metadata and transparent cost and licensing notes; no ACX claims | `test_narration_chunks_keep_alignment_and_announce_unreadable_content`; `test_narration_with_test_engine_exports_aligned_audio` (WAV per chapter, `chapters.json` with part offsets and block IDs, `book.cue`, `NOTES.txt` with cost, licences, AI-voice disclosure and "Not checked against ACX/Audible or KDP audiobook requirements"; a new revision makes old audio stale); cost from the entered price only (`test_cloud_speech_and_transcription_when_allowed`), "unknown" otherwise |
| Recorded interviews: owned audio, an explicitly configured engine, speaker correction, timestamps and links kept, quotations as sources, never fabricate speech | `test_recording_rights_transcript_speakers_and_quote_as_source` (rights required; non-audio refused; the test engine labels its text "not real speech"; speaker rename for one or all segments; **an UPDATE of transcript text is rejected by the database trigger**; quotation → knowledge source with exact text and timestamps; re-transcribing refused while quotations exist; the audio streams back) |
| Keep core publishing intact | the full suite, including every Phase 01–07 test and Playwright spec, passes unchanged apart from the schema head (`0008` → `0009`) |

## Phase 08: what was built

**Core**
- Migration `0009_advanced`: series, canon, continuity, translation, narration and recording tables; `author_profile.pen_name` and `voice_rules_json`; trigger `transcript_segment_immutable`.
- `series/continuity.py`, `services/series.py` and `api/routes_series.py`.
- `translation/protect.py`, `jobs/translation_exec.py` (job kind `translate_chapter`, dispatched in `jobs/execute.py`) and `services/translation.py`.
- `services/voice.py`: pen name, rules, and the active voice per book; rules added to prompts (`jobs/prompts.py`, `jobs/writing_exec.py`).
- `media/engines.py`, `media/narration.py` and `services/media.py`.
- `api/routes_advanced.py` (voice, editions, chapter links, narration, recordings, media status).
- The mock provider returns a labelled stand-in translation.

**UI**
- **Series** in the main menu: series list; per series, Books, Story bible (with suggestions and earlier values), Relationships (list plus map) and Continuity review.
- Book page: links to **Translations**, **Narration** and **Recorded interviews**, and a **Voice and series** panel.
- Author voice: pen name and do/avoid rules.
- Chapter editor: opens with a passage selected from `?select=start-end`, and an "Other languages" panel.
- New `api/advanced.ts`; `styles/advanced.css`.

**Docs**
- ADR-0009 (with the OpenAI audio API facts and the date they were read).
- SECURITY §7g, DATA_MODEL §3.9–3.10, ARCHITECTURE §7.6, TEST_PLAN §4.4e.
- README "Series, translations, narration and interviews (Phase 08)", with the optional tools table.

## Decisions taken in Phase 08 (need your validation)

| # | Decision | Why | Reversible? |
|---|---|---|---|
| P8-1 | Continuity review is rule-based (traits, age, death, kinship, chronology), not model-based | Reproducible, offline, free, and never invents a contradiction; findings are questions, not verdicts | Yes (a model-based reviewer could add suggestions later) |
| P8-2 | A finding's identity is rule + canon reference + chapter + normalised sentence; editing that sentence makes a new finding | Keeps decisions across re-runs without guessing whether a rewritten sentence is "the same" problem | Yes |
| P8-3 | Changing a canon value writes a new fact and supersedes the old one | Canon history and provenance are never lost | No (by design) |
| P8-4 | A book belongs to at most one series | Keeps "which canon applies" unambiguous | Yes |
| P8-5 | A translated edition is a full, separate book (its own chapters, revisions, exports) linked by chapter | Independent revisions and publishing per language; the original cannot be overwritten | Costly later |
| P8-6 | "Approved original" = the head of a chapter marked Approved, or any revision labelled "Approved" | Uses existing approval and revision labels; no new workflow | Yes |
| P8-7 | Translation output is a normal proposal; the suggested chapter title is shown, not applied | AI never silently overwrites; titles stay the author's call | Yes |
| P8-8 | Narration is synchronous, a few parts per request (no background job) | Local engines are fast; progress is visible per part; no audio job type in the queue | Yes |
| P8-9 | Audio is WAV only, one file per chapter, plus `chapters.json` and a cue sheet | Lossless and readable everywhere without FFmpeg; no claim of store readiness | Yes (MP3 via FFmpeg later) |
| P8-10 | No built-in audio prices; cost = the author's entered price, else "unknown"; local engines cost 0 | Never fabricate costs | Yes |
| P8-11 | Transcripts must have timestamps: OpenAI `whisper-1` or the diarize model only; other models are refused | Quotations must link to a time in the audio | Yes |
| P8-12 | Transcript text and timestamps are immutable; only speaker names change; re-transcribing is blocked while quotations exist | Never fabricate or alter speech; sources stay traceable | No (by design) |

## Known limitations (Phase 08, honest list)

1. **No real speech or transcription engine was run.** eSpeak NG, Piper and Whisper are not installed on this machine, so only their "not installed" paths and command construction were exercised. OpenAI audio was exercised against a recorded wire format (mock transport), not the live API. Audio quality is unverified.
2. **The continuity rules are narrow and English-centric.** Colour words, "N years old", a fixed verb list for "acting while dead", and "B's <kin> A" kinship phrasing only. Pronoun-only sentences ("Her eyes were brown") are not linked to a character. The review is a helper, not a full read.
3. **Translation quality was not evaluated.** The test model returns a labelled stand-in. Name, term and structure checks are heuristic and may flag false positives.
4. **Narration reads the Markdown structure, not a performance script.** No pronunciation lexicon, SSML, pauses between chapters, or loudness normalisation. Exports are not checked against ACX, Audible or KDP audiobook requirements.
5. **Recordings:** duration is read only from WAV headers (other formats show "—" until transcribed). Files over 25 MB cannot go to OpenAI (split them first). No waveform view and no timestamp-click seeking yet.
6. **Per-book backups (Phase 02) do not yet include Phase 08 data**: series canon, continuity decisions, edition links, narration parts and audio, recordings and transcripts. A translated edition is its own book and can be backed up on its own. The database snapshot taken before each migration covers everything. Adding these to the backup format is a Phase 09 candidate.
7. Real Ollama and cloud text models remain unexercised (see Phase 03).
8. My visual check created two demo books and a demo series ("Tides of Salt (demo)") in the dev workspace (`.pbs-data`, git-ignored). I looked at the relationship map, the continuity review, a passage link opening the editor with the sentence selected, and the narration page with no engine installed.

## Phase 08: bugs found and fixed

- **A nested database transaction deadlocked the cloud audio path** ("database is locked"): the permit check opens its own transaction and was called inside one. It now runs after the transaction closes.
- **Two schema names clashed in the API** (Phase 06 `FactIn`/`FactOut`/`FactPatch` and the new canon facts), which renamed the Phase 06 types and broke the writing UI types. The canon contracts are now `CanonFact*`.
- **A canon fact's value shared one text node with its Edit button**, so it could not be picked out on its own (found by the end-to-end test). The value now has its own element.
- **Passage links selected one character too many** (the space before the sentence), seen in the visual check. Sentence offsets are now trimmed to the sentence.
- **Buttons at the end of a form row stretched to fill their grid cell**, and the Phase 08 pages had no spacing between panels (visual check). Both fixed, with the button rule scoped to Phase 08 forms so earlier pages are unchanged.

## Phase 09 handoff

Preserve:
- canon status and provenance, supersession, and fingerprinted decisions;
- translation only from approved revisions, as proposals, with protected spans;
- media engines opt-in, gated and honest about cost and compliance;
- transcript immutability.

Next candidates:
- install and verify eSpeak NG, Piper and Whisper on a test machine;
- a pronunciation lexicon;
- MP3/M4B export via FFmpeg with chapter markers;
- a waveform and seek view for transcripts;
- a model-assisted continuity reviewer that only adds suggestions;
- per-language publishing profiles for editions;
- Phase 08 data in per-book backups (limitation 6).

---

## Phase 07 evidence (real results, 2026-11-22, Windows 11, CPython 3.12.13, Node 26.13)

Command: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1` → **exit 0, "All checks passed."**

| Check | Result |
|---|---|
| ruff lint / format (Core) | All checks passed / 165 files already formatted |
| mypy `--strict` (130 source files) | Success: no issues found |
| import-linter | 4 kept, 0 broken |
| pytest (Core) | **255 passed, 1 skipped**. The skip is the Ollama smoke test (no local Ollama). **No expected failures remain**: golden steps 11–13 now run |
| License gate | passed: 98 runtime dependencies (new: `typst` Apache-2.0, `pillow` MIT-CMU, `python-docx` MIT moved from dev to runtime) |
| ESLint (jsx-a11y strict) + Prettier, TypeScript strict | clean |
| Vitest + RTL + axe-core | **43 passed** (1 new file, `Publish.test.tsx`) |
| Vite production build | built |
| Playwright + axe (WCAG 2.2 AA tags) | **16 passed** (new `publishing.spec.ts`) |
| Migrations | head `0008`; fresh → head, head → head no-op, models ≡ migrations, upgrade with a snapshot |

### KDP specifications used (fetched and read 2026-11-22)
Rule set **`kdp-paperback-2026-11-22`** in `pbs_core/publishing/kdp_rules.py`. It is shown in the UI and in every report. The sources are listed with what each one supplied in ADR-0008:
- GVBQ3CMEQW3W2VL6 (trim, bleed, margins);
- G202145060 (print manuscript);
- G202187850 and G201953020 (print cover);
- G5HDYGP4BXLX4RUW (barcodes);
- G202131170 (Kindle Previewer);
- G200645690 (eBook cover);
- G200672390 (content and AI guidelines);
- G201298500 and G201097560 (keywords, metadata).

Not published by KDP (reported as manual checks, never invented): the exact barcode position, hardcover wraps, and a per-keyword character limit.

### Prompt 07 acceptance → evidence

| Acceptance item | Where it is proven |
|---|---|
| Export a fixture with 3 chapters, tables, images, math, code and citations to all five primary formats | `test_fixture_exports_to_all_five_formats_and_each_is_inspected`: Markdown, HTML, EPUB, DOCX and print PDF built from one assembly; a second build gives byte-identical HTML/EPUB/DOCX/PDF; a report is saved beside every file. Playwright `publishing.spec.ts` builds all five from the UI (no image there). Golden step 11 |
| Programmatically inspect PDF size, EPUB contents and DOCX paragraphs/styles | Same test. **PDF** (pypdf): every page 432 × 648 pt (6 × 9 in), page count = recorded count, `/Lang en`, not encrypted, all fonts embedded, chapter titles, caption numbers, the printed link address and citation in the text. **EPUB** (zipfile + lxml): `mimetype` first and stored, `dc:title`/`dc:language`, MathML accessibility feature, nav, 3 chapter files, alt text on the image, MathML, the cross-chapter link rewritten to `chapter-001.xhtml#fuel-and-air-tbl-mix`, numbered caption. **DOCX** (python-docx): Heading 1 chapter order, styles `PBS Code`/`PBS Equation`/`Caption`/`Title`, the code line in `PBS Code`, 2 tables, picture `descr` = alt text, external hyperlink relationship. Fidelity: Markdown/HTML/EPUB ok; DOCX "degraded" (equations kept as LaTeX source), PDF "degraded" (links printed as addresses); nothing missing |
| A print cover recalculates after the final PDF page count changes | `test_print_cover_recalculates_when_the_final_page_count_changes`: no cover without a PDF (409). With the first PDF (N pages): spine = N × 0.002252 in, and the cover PDF width equals the spec. The chapter grows → the new PDF has more pages → the cover spec follows the new PDF, the full width grows, the old cover is flagged stale ("build it again"). Building again gives a PDF of the new width, linked to the new interior. The eBook cover is 1600 × 2560 px. Playwright: the cover tab says it is sized from the final page count, and builds |
| Validate EPUB via an available tool or mark "validation unavailable", never "passed" | `test_epub_validation_is_unavailable_never_passed_without_epubcheck`: without EPUBCheck → "unavailable … This is not a pass"; with a validator that exits 1 → "fail" with its output. On this machine EPUBCheck is not installed, so every report says "unavailable" (Playwright checks the row in the report) |
| Produce and open the sample publish package and preflight report | `test_publish_package_has_everything_and_publishes_nothing`: the folder holds book exports (MD zip, HTML, EPUB, DOCX, interior PDF), the print cover, proof and eBook cover, `metadata.json`/`.txt`, `preflight-report.json`/`.html`, `COPYRIGHT-AND-LICENSES.txt`, `SOURCES.txt`, `KDP-UPLOAD-STEPS.md` and `manifest.json` (SHA-256 per file, `auto_publish: false`); the report opens inline; the ZIP downloads. Playwright builds the package in the UI and **opens the preflight report** (disclaimer, EPUBCheck unavailable, page count below KDP's 24-page minimum shown as a fail). Also opened by hand in the desktop browser pane |

### Other Phase 07 requirements → evidence

| Requirement | Evidence |
|---|---|
| Configurable front and back matter; no fabricated ISBN, copyright, endorsements or legal statements | 18 matter kinds (ADR-0008 §2). `test_front_matter_never_invents_legal_text_or_isbn`: with nothing entered, the copyright page is left out and reported; no "All rights reserved", "ISBN" or "Copyright ©" in the output; an invalid ISBN check digit → 422; a valid ISBN becomes the EPUB identifier |
| Interior templates (trim, fonts/licensing, heads/feet, chapter openings, page numbers, TOC, mirrored margins, images, numbering, code/math) | `publishing/book.TEMPLATES` (4) and `write_typst`. Font licenses are in every package. The gutter is raised to KDP's minimum for the final page count. Code-overflow and equation-as-source checks |
| Live HTML reading preview and print preview; warn if not byte-identical | `test_previews_say_whether_they_match_the_export` (no export yet → null; after export → identical; after an edit → "Not identical…"); the PDF page preview says it is a page image, not the PDF file. Vitest and Playwright |
| Round-trip fidelity; never silently omit | `publishing/fidelity.py`; `test_unsupported_math_is_printed_as_source_and_reported` |
| Cover designer: licensed artwork or configured generator; editable typography; wrap and eBook covers; barcode, bleed and spine constraints; manual-check warnings | `test_cover_artwork_needs_rights_and_its_resolution_is_checked` (rights confirmation required; a 60 × 90 px artwork fails the 300 DPI check; barcode area "manual"). No image generation provider exists, and the UI says so |
| Preflight (PDF dims/count, bleed/margins/gutter, fonts, image DPI, language, missing assets, overflow, cover dims, EPUB nav/metadata/links, DOCX validity, EPUBCheck) and a saved report per export | `publishing/preflight.py`; reports saved beside files and in `publication.report_json` |
| Metadata handoff (title, author, description, 7 keywords, unverified categories, age, language, format, AI checklist) | `test_metadata_handoff_checks` (8 keywords or 4 categories → 422; URL in the description → fail; "bestseller" or a title repeat in keywords → warn; categories → manual; AI questions unanswered → warn) |
| Package with exports, covers, metadata, report, license notes, sources and manual upload steps; no auto-publish | as above; `KDP-UPLOAD-STEPS.md` states PBS publishes nothing and that preflight is not approval |
| MOBI/AZW3 optional only | not built (no converter installed; KDP takes EPUB); stated in the UI and the profile `tools` |

## Phase 07: what was built

**Core**
- Migration `0008_publishing`: `publishing_profile` and `publication`.
- `publishing/`:
  - `kdp_rules` (versioned specs and sources), `book` (assembly, templates, matter, numbering, citations);
  - writers `write_markdown`, `write_html`, `write_epub`, `write_docx`, `write_typst`, and `latex_typst`;
  - `fidelity`, `preflight`, `cover`, `metadata`, `package`.
- `services/publishing.py` and `api/routes_publishing.py`: profile, build, cover spec, covers, package, publications, reports (JSON and HTML), files (download or inline), package files, HTML preview and PDF page preview.
- New runtime dependencies: `typst`, `pillow`, `python-docx`.

**UI**
- **Publishing** in the main menu (the last "not yet implemented" item is gone).
- **Publish** page per book with five tabs: Book setup, Store details, Cover, Build and preview, Publish package.
- A "Publish" link on the book page.

**Docs:**
- ADR-0008, and ADR-0003 marked accepted (Typst).
- SECURITY §7f, DATA_MODEL §2.3d, ARCHITECTURE §7.5, TEST_PLAN §4.4d.
- README "Publishing (Phase 07)".

## Decisions taken in Phase 07 (signed off)

Signed off by the user on 2026-11-22: all recommendations P7-1 to P7-10 below are accepted as recorded.

| # | Decision | Why | Reversible? |
|---|---|---|---|
| P7-1 | Typst (Python wheel) is the print-PDF engine; no WeasyPrint or Pandoc | Works offline on this machine, deterministic, embeds fonts, tagged PDF (ADR-0003 spikes) | Costly later |
| P7-2 | Own EPUB and DOCX writers instead of Pandoc | Pandoc is not installed, and the writers share PBS's numbering and citations | Yes |
| P7-3 | Fonts limited to Typst's built-in, freely licensed set | Reproducible builds, licenses known; no system fonts | Yes (bundle more OFL fonts) |
| P7-4 | DOCX equations as LaTeX text; footnotes as chapter-end notes | No reliable native Word-equation path here; reported as "degraded" | Yes |
| P7-5 | The print PDF has no live links or bookmarks; links print their address | KDP asks for no annotations or bookmarks in print files | Yes |
| P7-6 | No interior bleed; paperback covers only | Nothing in PBS needs edge-to-edge interior art; hardcover wraps are not published by KDP | Yes |
| P7-7 | The barcode area is reserved bottom-right of the back cover (2 × 1.2 in, 0.25 in in) and marked "check manually" | KDP gives the size and margins but not the position | Yes |
| P7-8 | Covers are RGB; CMYK conversion is not done | No colour-managed conversion available; a printed proof is the real check | Yes |
| P7-9 | The copyright page appears only with author-entered details | "Do not fabricate legal statements" | Yes |
| P7-10 | Preflight statuses include "manual" and "unavailable", and these never count as pass | Honest reporting | No (by design) |

## Known limitations (Phase 07, honest list)

1. **EPUBCheck is not installed here**, so EPUB validation is "unavailable" in every report. PBS's own EPUB checks (container, metadata, manifest, nav, XHTML, links, alt text, accessibility metadata) did run. Kindle Previewer is a manual step.
2. **PDFs are not PDF/X-1a, and colours are RGB.** Fonts are embedded as subsets (KDP recommends full embedding). Each is reported as a warning or manual check.
3. **DOCX:** equations are LaTeX text, the table of contents is a Word field (update it in Word), and footnotes are chapter-end notes.
4. **The LaTeX → Typst converter covers a subset.** Other equations print as LaTeX source and are reported.
5. **Text overflow is checked for code lines only** (by character width). Long unbreakable words or URLs in body text are not measured.
6. **No hardcover**, no interior bleed, no spot colours, no MOBI/AZW3.
7. **The KDP rules are a snapshot from 2026-11-22.** The package tells the author to compare with the live pages and KDP's cover calculator.
8. **Images inside chapters** are capped at 300 DPI print size, so small images print small rather than blurry.
9. Real Ollama and cloud models remain unexercised (see Phase 03).
10. My visual check built a publish package for “The Quiet Engine” in the dev workspace (`.pbs-data`, git-ignored) and opened its preflight report and eBook cover in the desktop browser pane.

## Phase 07: bugs found and fixed

- **Blank left-hand pages** before chapters showed a running head and page number (visual check of the first PDF); they are now clean.
- **A bibliography label** inside a Typst list made layout fail; print bibliographies no longer carry labels. Layout failures are now reported as a clear 409, not a 500.
- **Cross-chapter links** were not resolved, and EPUB file links were rendered as "unsafe" text. Anchors now resolve across chapters, and links between the book's own files are allowed.
- **PDF bytes changed between identical builds** (Typst used the current time). The PDF date now comes from the book's last revision.
- **The accessibility scan hung** on the sandboxed reading-preview iframe (test tooling); the iframe is excluded from the scan.
- **The package folder path ran off the page** on narrow windows (visual check); it now wraps.
- **A Phase 03 UI test was flaky under full-suite load** (a 5-second announcement could clear before it was checked); it now waits for the announcement right after the click.

## Phase 08 handoff

Preserve:
- `publication` rows and reports, the rule-set versioning, and `cover_spec` from the final page count;
- "unavailable" and "manual" never counting as pass;
- no auto-publish.

Next candidates:
- bundle more OFL fonts;
- a colour-managed CMYK cover path;
- EPUBCheck in CI;
- PDF/X;
- hardcover once KDP's specifications are checked.

---

## Phase 06 evidence (real results, 2026-11-22, Windows 11, CPython 3.12.13, Node 26.13)

Command: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1` → **exit 0, "All checks passed."**

| Check | Result |
|---|---|
| ruff lint / format (Core) | All checks passed / 145 files already formatted |
| mypy `--strict` (112 source files) | Success: no issues found |
| import-linter | 4 kept, 0 broken |
| pytest (Core) | **242 passed, 1 skipped, 3 xfailed**. The skip is the Ollama smoke test (no local Ollama). The xfails are golden steps owned by Phase 07 |
| License gate | passed: 94 runtime dependencies (no new dependencies) |
| ESLint (jsx-a11y strict) + Prettier, TypeScript strict | clean |
| Vitest + RTL + axe-core | **40 passed** (1 new file, `Write.test.tsx`) |
| Vite production build | built |
| Playwright + axe (WCAG 2.2 AA tags) | **15 passed** (2 new specs in `writing.spec.ts`) |
| Migrations | `test_migrations.py`: fresh → head `0007`, head → head no-op, models ≡ migrations (no drift), older DB upgraded with a snapshot |

### Prompt 06 acceptance → evidence

| Acceptance item | Where it is proven |
|---|---|
| Generate a short 3-chapter test book, stop, resume, and inspect the draft job history | pytest `test_three_chapter_book_by_section_with_pause_resume_and_history`: wizard book with 3 chapters → AI outline (test model) → whole-book run → 3 plans of 2 sections; the first section is done, the draft is **paused** (the queued second section is cancelled and returns to pending; nothing runs), **resumed** (the finished section is not sent again) → all three chapters assembled into one suggestion each, no chapter changed. The history lists every attempt (`1. attempt 1 succeeded`, `2. attempt 1 cancelled (paused)`, `2. attempt 2 succeeded`) with provider, model, template, token usage and the job log ("Context for section 1 …", "stored on the draft plan (not in the chapter)"). Later chapters' prompts carry summaries of earlier ones. Playwright "Phase 06 acceptance": the same in the UI with the review gate (pause, resume, edit and approve each section, open the job history) |
| Generated content does not supersede locked or approved material | `test_locked_and_approved_chapters_are_never_superseded`: an approved chapter with text and a locked chapter are skipped with reasons; a one-chapter run on the approved chapter and an AI request on the locked one are refused (409). A chapter locked **after** drafting: its suggestion is "not applicable" and Accept is refused; its revision count, and the approved chapter's text, are unchanged. Unlocking allows the accept (revision 1). Playwright: the locked "Tools" chapter is skipped and has no suggestion |
| Mark and review at least two unsupported facts in test data | `test_unsupported_facts_are_marked_and_reviewed`: the fixture has two uncited factual sentences ("In 2019, 64% …", "Studies show … doubles …") and one cited paragraph; exactly the two are flagged. The author marks one "needs a source" (with a note) and dismisses the other; a re-run keeps both decisions (0 new). Citing the paragraph makes both "no longer found", with decisions kept. Playwright: two findings, decision set, still set after reload. Vitest: the decision is sent. The AI review path keeps only findings that quote the chapter (`test_ai_review_keeps_only_findings_quoted_from_the_chapter`: 1 kept, 1 invented quote dropped) |
| Run an intentional repeated-paragraph check and verify a real finding | `test_repeated_paragraph_check_finds_a_real_duplicate`: the same 21-word paragraph in two chapters → one `duplicate_paragraph` warning with both locations (chapter 1 paragraph 1, chapter 2 paragraph 2) and the exact excerpt; a phrase used three times → a `repeated_phrase` finding with count 3. Playwright: the repeated paragraph is found in the UI ("The same paragraph appears 2 times") |
| All tests, build and migration checks pass | the table above |

### Other Phase 06 requirements → evidence

| Requirement | Evidence |
|---|---|
| Draft by section with brief, local outline, prior chapter summaries, style guide, passages, story bible, targets and exclusions | `writing/memory.py`, `jobs/writing_prompts.section`; the context report per section; `test_three_chapter_book…` (summaries), `test_fiction_continuity_memory_and_checks` (continuity notes in the next chapter's prompt) |
| Structured plan and per-section jobs; retry failed sections without rewriting successful ones; pause, cancel, resume; review gates | `draft_plan` / `draft_section`; `test_failed_section_is_retried_alone` (a finished section's retry is refused with 409; its text and single attempt are unchanged), `test_review_gate_lets_the_author_edit_each_section` |
| Avoid context blowups: summaries, continuity memory, retrieval, explicit token budget | `test_token_budget_trims_context_and_reports_it` (a 600-paragraph chapter: "so far" trimmed, the end kept, used ≤ budget, prompt within budget) |
| Task, provider and model provenance | per-section provenance, the suggestion's `pipeline` provenance, job history |
| Draft only into a proposed revision | the assembled proposal; the chapter is unchanged until Accept (pytest and Playwright) |
| Editor actions with diff + accept/reject | `test_editor_actions_keep_code_and_math_and_show_a_diff` (clarity → replacement with a word diff; quiz → inserted after the selection; explain → note; tone without wording → 422); Playwright (diff shown with `<del>`/`<ins>`) |
| Quality reviews (grammar/style, repeated phrases, duplicates, unsupported claims, missing citations, outline/promise mismatch, broken links, alt text, terms, acronyms) | the tests above plus `test_links_alt_terms_acronyms_exclusions_and_gated_code_checks`; AI review for grammar and the reader's promise |
| Fiction: chronology, traits, location/relationship consistency, unresolved threads, timeline updates | `test_fiction_continuity_memory_and_checks` (green vs brown eyes → conflict; event years out of order → chronology; open thread; rejecting a note clears the conflict) |
| Technical: equations and code preserved; code checks only if authorised; unverified claims marked; AI review is not proof | protected placeholders (the test model dropping them → `invalid_output`, no suggestion); code checks skipped until allowed, then "the code was not run"; disclaimers in the API and UI |
| Originality report states its scope | `test_originality_report_states_its_scope` (overlaps with another workspace book and a knowledge source; scope, "not covered", no external provider, "does not mean the text is original") |

## Phase 06: what was built

**Core**
- Migration `0007_writing`: `draft_plan`, `draft_section`, `continuity_fact`, `chapter_summary`, `quality_finding`.
- `writing/`:
  - `pipeline.py`: queue a section, advance, assemble one proposal (with ledger claims, requirement check and summary), run ordering, cancel and stop;
  - `context.py`: token-budget fit and report;
  - `memory.py`: brief, local outline, chapter so far, earlier summaries, continuity notes;
  - `protect.py`: code and math placeholders;
  - `quality.py`: twelve local checks;
  - `originality.py`: the local overlap report;
  - `store.py`: finding upserts with stable fingerprints.
- `jobs/writing_prompts.py` (section and review prompts, JSON schemas) and `jobs/writing_exec.py` (prepare at run time, parse, commit). Two new branches in `jobs/execute.py`, plus placeholder masking for revise and translate.
- Phase 05 runs now create one draft plan per chapter, in order. Estimates count one model call per section within the token budget. Stopping a run cancels its plans.
- Editor actions (`action` on AI requests); word-level diff on replacement proposals; `chapter.locked` settable by the author, which blocks requests and accepts.
- `services/writing.py` and `api/routes_writing.py`: 20 new endpoints under `/api/projects/{id}/writing/…`.
- The test model answers section and review requests, and has new markers `[[mock:fail_once]]`, `[[mock:conflict]]` and `[[mock:drop_code]]`.
- Backup includes continuity notes, summaries and findings, with fingerprints recomputed on restore.

**UI**
- **Write and review** page (`/projects/:id/write`):
  - **Drafts**: per-section state, context report, review-gate editor, pause, resume, cancel, retry, job history;
  - **Story bible and summaries**: confirm, reject or resolve notes; add notes; edit summaries;
  - **Quality checks**: run (book or chapter), code-check permission, AI review, findings grouped by check with decision and note, disclaimers;
  - **Originality**: scope, not covered, statement, overlaps table.
- **Plan → Draft chapters**: "Stop after each section", the token budget, section counts in the estimate, and a link to the drafts.
- **AI assist**: an "Editor action on the selection" menu, an inline word diff on replacement suggestions, and a note when code or math was protected.
- **Chapter editor**: "Lock against AI changes".
- **Book page**: a "Write and review" link.

**Docs:** ADR-0007; SECURITY §7e; DATA_MODEL §2.3c; ARCHITECTURE §7.4; TEST_PLAN §4.4c; README "Writing and reviewing (Phase 06)".

## Decisions taken in Phase 06 (need your validation)

| # | Decision | Why | Reversible? |
|---|---|---|---|
| P6-1 | Generation runs always draft by section; the Phase 05 one-call-per-chapter path is gone | The brief says "not a single giant prompt" | Yes |
| P6-2 | Chapters in a run are drafted one after another, not in parallel | Each chapter can then use the previous chapter's summary | Yes |
| P6-3 | Sections return JSON (text, summary, facts) | One call yields the text, the summary and the continuity updates | Yes (a separate summary call is possible) |
| P6-4 | AI-extracted continuity notes are "proposed" until the author confirms; rejected ones are never sent | The author decides what is canon | Yes |
| P6-5 | A new author-set `chapter.locked` flag also blocks accepting a suggestion | "Never overwritten automatically" made explicit | Yes |
| P6-6 | Code and math are protected by placeholders; a reply that changes them is rejected, not repaired | Byte-for-byte preservation is guaranteed rather than hoped for | Yes |
| P6-7 | Code checks parse only (Python, JSON), off by default per book | No safe execution sandbox exists here | Yes, add a sandbox later |
| P6-8 | AI review uses the `revise` route, not a new task type | Avoids rebuilding the job table's CHECK constraint | Yes |
| P6-9 | Draft plans and section history are not in book backups | Working records, like runs and job logs | Yes |

## Known limitations (Phase 06, honest list)

1. **Section JSON depends on the model following instructions.** Bad replies are retried three times, then the section fails visibly (retry it). Only the test model was exercised here.
2. **Token counts are estimates** (four characters per token). A model with a context window smaller than the budget can still overflow; set the budget accordingly.
3. **Summaries are the model's own** section summaries and are not checked against the text. You can edit them.
4. **Continuity checks compare notes, not prose.** A trait changed only in the prose is caught only by an AI review or by you.
5. **The quality rules are English-centric heuristics**: the fact-like sentence rules, acronyms and term variants over- and under-flag. Grammar is covered only by the AI review; style hints are minimal.
6. **No code is executed.** Only Python and JSON are parsed.
7. **The originality report is local** (this book, your other books, this book's sources). There is no web or published-works comparison, and no external provider ships.
8. Drafting a chapter that already has text (one-chapter mode) appends the sections after the existing text.
9. Real Ollama and cloud models remain unexercised (see Phase 03).
10. My visual check ran the quality checks on “The Quiet Engine” in the dev workspace (`.pbs-data`, git-ignored). It found nothing, so no findings were stored.

## Phase 06: bugs found and fixed

- **Editor actions were applied twice** (in enqueue and again in planning), which moved the insertion point and rejected the request. Fixed by clearing the action after it is applied.
- **The section review box stayed empty** when it had mounted before its section finished (visual/e2e check). It now starts from the finished text.
- **The test model's failure marker leaked** into other sections through the outline text. It now matches only the section's own goal.
- **The story-bible note form wrapped awkwardly** in three columns (visual check). It now uses rows of two.

## Phase 07 handoff

Preserve:
- proposals as the only way AI text reaches a revision, and `chapter.locked`;
- the section pipeline and its context report;
- continuity notes and summaries as the source for cross-chapter context;
- finding fingerprints and decisions;
- the "not proof" disclaimers.

Start Phase 07 (publishing) from accepted revisions only. Use quality findings (missing alt text, broken links, unresolved images, missing citations) as preflight inputs, and citation metadata from Phase 04 for bibliographies.

---

## Phase 05 evidence (real results, 2026-11-22, Windows 11, CPython 3.12.13, Node 26.13)

Command: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1` → **exit 0, "All checks passed."**

| Check | Result |
|---|---|
| ruff lint / format (Core) | All checks passed / 129 files already formatted |
| mypy `--strict` (98 source files) | Success: no issues found |
| import-linter | 4 kept, 0 broken (the Open Library client lives in `pbs_core.providers`, behind the egress gate) |
| pytest (Core) | **228 passed, 1 skipped, 3 xfailed**. The skip is the Ollama smoke test (no local Ollama). The xfails are golden steps owned by Phase 07. Step 05 now passes |
| License gate | passed: 94 runtime dependencies (no new dependencies; Open Library is called with the existing `httpx2`) |
| ESLint (jsx-a11y strict) + Prettier, TypeScript strict | clean |
| Vitest + RTL + axe-core | **37 passed** (9 files; 2 new: `lib/outline.test.ts`, `Plan.test.tsx`) |
| Vite production build | built |
| Playwright + axe (WCAG 2.2 AA tags) | **13 passed** (2 new specs in `planning.spec.ts`) |

### Prompt 05 acceptance → evidence

| Acceptance item | Where it is proven |
|---|---|
| From a new idea, build and approve a detailed outline with a deterministic test adapter, without paid API access | pytest `test_idea_to_approved_outline_with_test_model` and golden step 05. Playwright "Phase 05 acceptance": New Book wizard → brief (prefilled from the wizard) → Approve brief → AI outline proposal from the built-in test model → Approve → Apply → three planned chapters. No API key exists in the test run, and the egress counter stays at zero |
| Unsupported market metrics are never fabricated | `test_ai_brainstorm_cannot_carry_market_metrics`: the test model is made to claim sales rank, search volume and "bestseller" status (`[[mock:metrics]]`). Every such sentence is removed and flagged, and an item that was only a claim is dropped. Writing `metrics_json` on an AI row, or marking an AI finding measured, is refused **by DB CHECK constraints**. Also `test_ai_finding_cannot_become_measured`, `test_author_findings_separate_measured_from_heuristic` (an unsourced figure the author types is flagged `unsourced_metric` and shown as opinion), and `test_open_library_results_keep_bibliographic_data_only` (reading-log and rating fields are never requested or kept) |
| An approved outline becomes a durable chapter skeleton; a changed outline does not destroy prose or revision history | `test_changed_outline_keeps_prose_history_and_locks`: write prose → rename, move and remove nodes → approve v2 → apply. The chapter with prose is renamed with its text and revisions intact, the removed chapter with prose is **kept** and reported, the empty one is archived, and the locked one is untouched. `test_ai_regeneration_never_overwrites_draft_and_keeps_locked`. Playwright: prose and History survive a rename and a removal |
| Fail-safe behaviour on an unavailable research provider is explicit | `test_research_provider_off_blocked_or_down_fails_explicitly`: off → 409 `research_unavailable` with reason `not_configured`; local-only mode → `blocked` (zero egress); provider outage → `failed`. Each says nothing was searched or added, adds no findings, and is logged in `research_query`. Playwright: the Research tab shows "… is not turned on. Nothing was searched" and the measured list stays empty |

### Other Phase 05 requirements → evidence

| Requirement | Evidence |
|---|---|
| New Book wizard with all requested fields | `NewBookPage.tsx` (four steps); `test_wizard_creates_book_brief_and_links_sources`; Playwright (axe clean) |
| Research workspace: topic finder, query drafting, providers only when configured, editable findings with source/date/URL, competitor notes, KDP keyword brainstorming | Research tab; `POST …/research/ideas` (topics, queries, keywords, each flagged `ai_brainstorm_not_measured`, keywords also `no_search_volume_data`); `PATCH …/findings/{id}`; "Save as comparable title" copies from the server-side query log |
| Heuristic observations kept apart from measured evidence | API `evidence` field ("measured" / "heuristic"); two separate UI regions; DB CHECK: measured ⇒ named source |
| Brief with target reader, promise, exclusions, value proposition, teaching or plot arc, explicit assumptions | Brief tab; `test_brief_approval_and_new_version_on_change` |
| Outline: stable IDs, drag-reorder, merge/split, hierarchy, chapter goals, target words, estimated writing work | `lib/outline.ts` + Vitest (IDs kept on move, merge keeps the first ID, split, nest/un-nest, locked entries never merged or split); server validation `test_outline_structure_is_validated`; totals with hours labelled as estimates |
| Approval before any bulk generation | `test_bulk_generation_requires_an_approved_applied_outline` |
| Nonfiction source/citation requirements; fiction plot, character and continuity requirements | Per-node `requirements` in the outline; `requirements_check` stored with each chapter proposal (citations found vs required, characters named; plot and continuity marked "review yourself") |
| Cost and time previewed as estimates; hard budget cap; chapter limit | `test_budget_cap_blocks_and_stops_runs` (unknown cost, currency mismatch and over-cap estimate refused; reaching the cap mid-run cancels the queued chapters), `test_chapter_limit_blocks_large_runs`; Playwright estimate table ("Local model: no API charge") |
| Outline-first, one-chapter and entire-book modes honour manual edits and locks | `test_entire_book_honours_prose_locks_and_review` (locked, approved, unsaved-draft and prose chapters skipped with reasons; output is proposals only). Playwright: "Every eligible chapter" → suggestions wait for review and nothing is written |
| Backup | `test_backup_restore_keeps_brief_findings_outlines_and_links` |

## Phase 05: what was built

**Core**
- Migration `0006_planning`: `book_brief`, `research_finding` (with the metric and measured-source CHECKs), `research_query`, `outline_version` (one approved per book, partial unique index) and `generation_run`. `migrations/env.py` now excludes the FTS5 shadow tables from autogenerate.
- `planning/`:
  - `outline.py`: tree validation (part > chapter > section, at most 500 nodes), stable `n_<ULID>` IDs, totals, keeping locked nodes;
  - `skeleton.py`: applies an approved outline to chapters without touching prose;
  - `research.py`: the market-metric guard;
  - `runs.py`: the budget stop and requirement checks.
- `providers/research_adapters.py`: the Open Library adapter (bibliographic fields only, generic User-Agent, `openlibrary.org` on the egress allowlist) and a dev/test catalogue that can simulate an outage.
- Planning jobs (`outline`, `research_ideas`) on the existing job runner: `jobs/planning_prompts.py` (schemas, "no market data" rule) and `jobs/planning_exec.py`. Chapter drafting from the outline uses the normal chapter job path with run, node and requirements context; each finished chapter records its actual cost against the run.
- `services/planning.py` and `api/routes_planning.py`: 23 new endpoints (102 API paths in total), including `POST /api/books` for the wizard.
- Backup includes the brief, findings and every outline version.

**UI**
- **New book** wizard: the project form plus "Reader and promise", "Shape and sources" and "Approvals and budget".
- **Plan** page per book, with four tabs:
  - **Brief**, with approve and versioning;
  - **Research**: measured evidence, notes and ideas (heuristic), public catalogue search, and AI brainstorm;
  - **Outline**: the AI proposal with approve, edit or reject; your draft, with drag handles, Up/Down/Indent/Outdent, merge, split, add, remove, lock, goals and requirements; the approved outline with "Apply to manuscript" and an apply report;
  - **Draft chapters**: one chapter or every eligible chapter, an estimate table, then runs with status and Stop.
- **AI settings**: a "Research search" section to turn Open Library on (needs cloud allowed).
- Navigation: Research is no longer "not implemented"; the book page links to Plan.

**Docs:** ADR-0006; SECURITY §7d; DATA_MODEL §2.3b; ARCHITECTURE §7.3; TEST_PLAN §4.4b; README "Planning a book (Phase 05)".

## Decisions taken in Phase 05 (need your validation)

| # | Decision | Why | Reversible? |
|---|---|---|---|
| P5-1 | Outline sections stay inside their chapter (as `##` headings); only parts and chapters become chapter rows | One document per chapter; no tiny section documents | Yes |
| P5-2 | Open Library is the only real research provider, off by default, and it needs `cloud_allowed` | Free and keyless, with bibliographic data only; no licensed market-data source exists | Yes, add adapters behind the egress gate |
| P5-3 | Time estimates come only from this workspace's measured throughput; otherwise "unknown" | No guessed speeds | Yes |
| P5-4 | An unknown cost blocks a run when a budget cap is set (before and during the run) | A cap that cannot be checked is not a cap | Yes |
| P5-5 | Entire-book mode skips chapters that already have text; one-chapter mode may append to one | Bulk runs never pile onto your prose | Yes |
| P5-6 | Metric statements in AI brainstorms are removed (and flagged), not just labelled | "Never fabricate" is stronger than "label as fabricated" | Yes |
| P5-7 | The brief's kind is derived from the project type (fiction/serial → fiction; course/technical → manual) | One source of truth | Yes |
| P5-8 | Every drafted chapter is a proposal, whatever the approval preference | "AI never silently overwrites" | Yes (a batch-accept could come later) |

## Known limitations (Phase 05, honest list)

1. **No licensed market data.** Sales rank, demand, competition and search volumes are "not available" by design.
2. **Plot points and continuity are not machine-checked**; the requirement check marks them "review yourself".
3. **Outline generation is one model call.** Very long books depend on the model's output limit.
4. **The first run on a model always shows "time unknown"** (no throughput history yet).
5. **Research query logs and generation runs are not backed up** (findings, briefs and outlines are).
6. Open Library was not called live (the adapter is tested through a mock transport with its documented response shape and a simulated connection failure; the socket guard forbids real network in tests).
7. Real Ollama and cloud models remain unexercised here (see Phase 03).
8. My visual check opened a hand-written outline draft on "The Quiet Engine" in the dev workspace but did not save it, so nothing was added.

## Phase 05: bugs found and fixed

- **Alembic autogenerate tried to drop the FTS5 tables** from Phase 04. They are now excluded in `migrations/env.py`.
- **The dollarmath plugin crashed on text ending in a backslash** (its escape check read `src[-1]`). Patched in `bookmd.py`, with a regression test.
- **Nested-transaction deadlock** when listing research providers inside a request transaction. It now reads in the same session.

## Phase 06 handoff

Preserve:
- outline node IDs and `chapter.outline_node_id` as the link between plan and manuscript;
- the skeleton rules (never touch prose; keep, don't delete, chapters with text);
- proposals as the only way AI text reaches a revision;
- the budget stop in `runs.record_cost` and the run's skip reasons;
- the market-metric guard and the measured/heuristic split;
- research only through the egress gate, failing explicitly.

Start Phase 06 from `generation_run` and the per-node requirements: they are the natural inputs for multi-step chapter jobs (`job_step`, deferred since Phase 03) and for continuity checks across chapters.

---

## Phase 04 evidence (real results, 2026-11-22, Windows 11, CPython 3.12.13, Node 26.13)

Command: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1` → **exit 0, "All checks passed."**

| Check | Result |
|---|---|
| ruff lint / format (Core) | All checks passed / 115 files already formatted |
| mypy `--strict` (86 source files) | Success: no issues found |
| import-linter | 4 kept, 0 broken |
| pytest (Core) | **210 passed, 1 skipped, 4 xfailed**. The skip is the Ollama smoke test (no local Ollama). The xfails are golden steps for Phases 05 and 07. Step 04 now passes |
| License gate | passed: 94 runtime dependencies (no new dependencies: FTS5 ships with SQLite, and voice analysis uses the standard library) |
| ESLint (jsx-a11y strict) + Prettier, TypeScript strict | clean |
| Vitest + RTL + axe-core | **29 passed** (7 files; 5 new) |
| Vite production build | built |
| Playwright + axe (WCAG 2.2 AA tags) | **11 passed** (2 new knowledge specs) |

### Prompt 04 acceptance → evidence

| Acceptance item | Where it is proven |
|---|---|
| Imported sources are searchable, cited by exact passage and removable | pytest: `test_import_preserves_original_and_records_anchored_chunks`, `test_pdf_passages_carry_page_numbers` ("p. 3"), `test_search_highlights_exact_passage_with_reasons`, `test_remove_and_reindex`, golden step 04. Playwright `knowledge.spec.ts`: import → search with `<mark>` → open the cited passage (highlighted) → cite → remove → search finds nothing, and the ledger quote shows "source removed". Also checked by hand in the desktop browser pane (highlighted hits with locator and match reasons) |
| Disabling a source prevents its use in new generations | `test_disabling_a_source_keeps_it_out_of_new_generations`: disabled **after queueing** and **before running** → the prompt has no passage, provenance lists no source, every paragraph is "unverified"; re-enabling restores it. Playwright: "Use for AI" off → "No source passages will be sent" → the card has no source links |
| A generated paragraph shows supporting sources or an explicit "unverified" flag | `test_generated_paragraphs_show_sources_or_unverified`: per-paragraph `supported` with key, locator and an exact quote found in the source, plus a trailing `unverified` paragraph; the text gets `[@torque-handbook, para. N]`. `test_fabricated_citation_is_dropped_and_flagged`. Vitest "Sources on a suggestion" (links to the passage, "Unverified" flag, removed-citation warning). Playwright |
| Style rewrite is preview-only until accepted; the original revision stays accessible | `test_style_rewrite_is_preview_only_until_accepted`: the chapter stays at revision 1 until Accept; afterwards `GET …/revisions/1` returns the original text; the proposal shows before/after (replace mode) |
| Tests cover provenance, injected malicious text, deduplication, backup/restore of citations | provenance (above); injection: `test_malicious_source_text_stays_data`, `test_forged_envelope_in_plain_text_source_is_neutralised`; deduplication: `test_deduplication_by_file_and_by_text`; backup/restore: `test_backup_restore_keeps_citations_sources_claims_and_answers` (same chapter text and `[@key]`, citations resolve, 2 claims with supports and quotes, search index rebuilt, interview answer kept, original book untouched) |

### Other Phase 04 requirements → evidence

| Requirement | Evidence |
|---|---|
| Per-book and shared opt-in libraries; tags, enable/disable, remove/re-index, indexing status | `test_books_only_see_their_own_and_opted_in_sources`, `test_unreadable_source_is_recorded_as_failed`; UI Sources, Knowledge and source pages |
| Chunks with headings and page/paragraph anchors; provenance; originals preserved | ADR-0005 §1; tests above |
| FTS5 search, highlighted passages, transparent match reasons; semantic search behind a capability flag | `search.py`; the API reports `semantic: "unavailable"` with a note (no embedding model) |
| Never fabricate titles, URLs, pages or DOIs | Titles from file metadata or name, labelled; bibliographic fields author-entered only (`test_source_metadata_is_only_what_the_author_enters`); locators only from real anchors; invented labels dropped |
| Evidence ledger separate from prose, with review state and stable keys; export of citation metadata | `claim` / `claim_support` tables, the Evidence page, `test_author_claims_link_to_exact_passages`, `GET /projects/{id}/citations` |
| Author voice: own writing only, analysis, editable guide, before/after, corrections | `test_samples_require_rights_confirmation`, `test_analysis_metrics_examples_and_editable_guide`, Vitest voice test, Playwright |
| Interview: exact answers with provenance; never invent experiences | `test_answers_are_exact_versioned_and_immutable` (DB trigger), `test_drafting_from_interview_uses_only_the_authors_words` |
| Injection isolation; escape external HTML | ADR-0005 §4, SECURITY §7c, the tests above, the Vitest search test (a `<script>` in a snippet renders as text) |

## Phase 04: what was built

**Core**
- Migration `0005_knowledge`: `knowledge_library`, `library_link`, `source`, `source_chunk`, the FTS5 table `source_chunk_fts`, `claim`, `claim_support`, `author_profile`, `voice_sample`, `interview_session`, `interview_question`, and `interview_answer` with immutability triggers.
- `knowledge/`:
  - `extract.py`: anchored paragraphs and chunks; never crosses a heading or a PDF page;
  - `search.py`: FTS5, safe queries, plain-text highlight segments, match reasons;
  - `retrieval.py`: eligible sources and answers, chosen at run time;
  - `citations.py`: checks markers, locates quotes, rewrites to `[@key, locator]`, gives per-paragraph status;
  - `voice.py`: deterministic style analysis.
- Services:
  - `knowledge.py`: libraries, import with dedupe, patch, remove, re-index, viewer, search, citation export;
  - `evidence.py`: the ledger;
  - `voice.py`;
  - `interview.py`, with a 10-question bank;
  - `backup_knowledge.py`.
- AI integration:
  - prompts carry passage, answer and style envelopes with neutralisation and citing rules;
  - the executor retrieves at run time, processes citations and records ledger claims in the proposal transaction;
  - accept/reject moves claims to in-text or discarded;
  - requests take `use_sources`, `use_interview` and `voice_profile_id`;
  - the estimate shows how many passages and answers will be sent.
- The test model cites provided passages and simulates a fake citation and a compromised model (`providers/mock_knowledge.py`).
- `api/routes_knowledge.py`: 31 new endpoints.

**UI**
- **Book → Sources**: add files (duplicate notice with "Add it anyway"), the source list with status, tags, "Use for AI", "Re-read file" and Remove, a search with `<mark>` highlights, locators and "why it matched", and shared-library opt-in.
- **Knowledge** (menu): shared libraries.
- **Source page**: passages with locators, the cited passage highlighted and focused, and author-entered bibliography fields.
- **Evidence ledger**: claims with support status, exact quotes linked to passages, review state, add-a-claim with a passage picker, and the cited-sources list.
- **Interview**: questions with verbatim answers, version history, your own questions, and a third-party consent note.
- **Author voice**: profiles, samples behind a rights checkbox, heuristic measures, exact example sentences, an editable style guide, and before/after corrections.
- **AI assist**:
  - choose whether to use the book's sources and the interview;
  - "Rewrite in a voice" when revising;
  - the estimate shows the passages to be sent;
  - suggestion cards show the passages behind each paragraph, "Unverified" flags, and a removed-citation warning.
- Navigation: Knowledge and Author voice are live. The book page links to Sources, Evidence ledger and Interview.

**Docs:** ADR-0005; SECURITY §7c; DATA_MODEL §2.3a; ARCHITECTURE §7.2; TEST_PLAN §4.4a; README.

## Decisions taken in Phase 04 (need your validation)

| # | Decision | Why | Reversible? |
|---|---|---|---|
| P4-1 | Lexical (FTS5) search only; semantic search reported as unavailable | No local embedding model is set up; never pretend | Yes, add embeddings via Ollama later |
| P4-2 | Citation "located" means lexical overlap ≥ 25% (at least 2 content words) with a sentence of the cited passage | Deterministic, explainable; a weak match is flagged, never hidden | Yes, tune the threshold |
| P4-3 | Retrieval happens when the job **runs**, not when it is queued | So disabling a source always takes effect | Yes |
| P4-4 | Citation keys are scoped to a book (or "shared") and never change | Restore keeps the keys without rewriting text | Costly later |
| P4-5 | A style rewrite is `revise` with a voice profile, not a new task | Avoids changing job/route CHECK constraints | Yes |
| P4-6 | Paragraphs without citations are always labelled "Unverified", even in fiction | The brief requires an explicit flag; wording is neutral | Yes (could hide for fiction) |
| P4-7 | Removing a source keeps a tombstone row and the original file | Ledger quotes keep their title; originals are immutable | Yes |
| P4-8 | Voice profiles are workspace-wide and not in book backups | They belong to the author, not a book | Yes |

## Known limitations (Phase 04, honest list)

1. **No semantic search** (capability flag `unavailable`). Synonyms and paraphrases are not found.
2. **Locating is lexical.** A faithful paraphrase that shares few words is flagged "not located"; the author decides.
3. Retrieval picks at most 6 passages (12,000 characters) per request from one query. There is no multi-step research (Phase 05).
4. **Chapter preview shows citations as `(key, locator)` text, not links**; links to passages live in the review pane, ledger and source page.
5. **No OCR**: scanned PDFs become failed sources with the reason. PDF headings are guessed from "Chapter …" lines only.
6. **No bibliography rendering yet.** Citation metadata is exported as JSON for Phase 07.
7. Interview questions come from a fixed bank plus the author's own. AI-suggested follow-up questions are not built.
8. **The voice analysis is English-centric** (reading ease, contractions).
9. Real Ollama and cloud models remain unexercised here (see Phase 03).
10. My visual check added a source ("torque-handbook") to "The Quiet Engine" in the dev workspace (`.pbs-data`, git-ignored). Remove it on that book's Sources page if unwanted.

## Phase 04: bugs found and fixed

- **Phase 03 restore bug:** restoring AI revisions into the same workspace violated the "proposal applied once" unique index. Restored revisions now get a new, consistent reference. Found by the citation backup test.
- **Importer output was Markdown-escaped** (`\[\[S7\]\]`, `\<`), which corrupted quotes and hid injected markers. Knowledge text is now the source's literal text.
- **A three-page PDF became one chunk citing "pp. 1–3".** Chunks now break at page boundaries.
- **Restore inserted interview questions before their session** (no ORM relationships). Parent rows are now flushed first.
- **Source action buttons stretched to full row height** (visual check).

## Phase 05 handoff

Preserve:
- retrieval at run time and the eligibility rules;
- envelopes and neutralisation for all untrusted text;
- citations only from provided labels, rewritten to stable keys;
- the ledger's copied quotes;
- immutable interview answers;
- the "unverified" flag.

Start Phase 05 with: the book brief and outline versions using the ledger and sources as research inputs; research findings stored as ledger claims with `kind` and provenance; and multi-query retrieval per outline node.

---

## Phase 03 evidence (real results, 2026-11-22, Windows 11, CPython 3.12.13, Node 26.13)

Command: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1` → **exit 0, "All checks passed."**

| Check | Result |
|---|---|
| ruff lint / format (Core) | All checks passed / 97 files already formatted |
| mypy `--strict` (71 source files) | Success: no issues found |
| import-linter | **4 kept**, 0 broken. New: network clients (`httpx2`, `openai`, `anthropic`, …) only inside `pbs_core.providers` |
| pytest (Core) | **186 passed, 1 skipped, 5 xfailed**. The skip is the Ollama smoke test (no local Ollama on this machine). The xfails are golden steps owned by Phases 04, 05 and 07. Steps 06, 07 and 15 now pass |
| License gate | passed: 94 runtime dependencies (adds `anthropic` MIT, `openai` Apache-2.0, `keyring` MIT, `httpx2` and their dependencies) |
| ESLint (jsx-a11y strict) + Prettier, TypeScript strict | clean |
| Vitest + RTL + axe-core | **24 passed** (6 files; 6 new AI tests) |
| Vite production build | built |
| Playwright + axe (WCAG 2.2 AA tags) | **9 passed** (2 new AI specs against a loopback Ollama stub) |

### Prompt 03 "done when" → evidence

| Requirement | Where it is proven |
|---|---|
| Choose a local model, draft a paragraph into a review pane, accept → chapter revision | Playwright `ai.spec.ts` "Phase 03 acceptance". In the UI: add Ollama (stub server on 127.0.0.1) → Test connection → Find models → open a chapter → AI assist → pick `stub-writer:1b` → Ask → suggestion card (chapter unchanged) → Accept → revision 2, History shows "AI-generated (accepted)". Also checked by hand in the desktop browser pane with the built-in test model |
| Cancel/retry and restart do not corrupt the chapter or double-apply | Playwright `ai.spec.ts` "cancel, retry and a Core crash…": cancel mid-stream → no suggestion; Retry; **hard-kill Core mid-stream** → restart → exactly one suggestion; a **double-clicked Accept** creates one revision. pytest: `test_process_restart.py::test_ai_job_survives_hard_kill_without_double_apply` (real process), `test_restart_recovers_running_jobs_without_double_commit`, `test_cancel_while_streaming_applies_nothing`, `test_database_refuses_applying_a_proposal_twice` (unique index), `test_rate_limit_is_retried_with_backoff` |
| Local-only mode makes zero external AI calls | `test_local_only_mode_makes_zero_external_calls`: with a cloud provider configured and a key stored, test connection, model refresh, estimate and enqueue all refuse **before** the transport is called; the egress counter and the session socket guard both read zero. Golden step 15 (full draft → accept run). The AI settings page shows "Requests sent to the internet since Core started: none" (asserted in Playwright) |
| Automated tests pass | above |

### Other Phase 03 requirements → evidence

| Requirement | Evidence |
|---|---|
| Adapters for Ollama, OpenAI, Gemini, Anthropic, Grok (and Groq); endpoints verified, not guessed | ADR-0004 §2, with the facts verified against the official docs on 2026-11-22 and the unverifiable ones listed. Contract tests per adapter over recorded wire formats (`test_ai_providers.py`): request shape (`max_completion_tokens`, `stream_options`, no `temperature` for Claude, Gemini key in a header), streaming, usage, structured output, refusals, error mapping (quota vs rate limit vs auth, `Retry-After`), Ollama mid-stream errors |
| Keys in the OS credential store; dev fallback with warning; never in DB/logs/Git/exports/backups | `security/secrets.py` (keyring default; `dev-file` opt-in with warning). `test_api_key_never_leaves_the_credential_store` scans the DB, WAL, logs, backup ZIP and entries, and exports for a canary key → 0 hits. The API never returns the key, and a 422 on a bad key does not echo it |
| Task routing; explicit selection wins; no silent fallback | `test_task_route_is_used_and_estimate_is_labelled`, `test_no_model_chosen_is_an_explicit_error`; revoking consent fails a queued job with `egress_blocked` without sending anything |
| Structured JSON with validation; capabilities checked, not assumed | Native schema only when the capability is reported, documented or declared. `test_structured_brainstorm_is_validated` (bad JSON → retried → `invalid_output` after 3 attempts) |
| Estimate before running; actual usage; "estimate" and "unknown" labels | `costs.estimate`; `test_cloud_needs_confirmation_and_project_consent` (no price → `null` "Unknown", then priced → `0.000038 USD` from reported usage); Vitest jobs page ("Unknown", no `%`) |
| Durable queue: IDs, stages, retries, provenance, recovery, cancellation, bounded concurrency | `jobs/runner.py` + `jobs/execute.py`; the tests above plus `test_recover_marks_exhausted_jobs_interrupted` |
| Status center with logs, retry, actionable failures, cost table | `/jobs` page (Vitest + Playwright, axe clean) |
| Project-scoped requests, content limits, user review | One chapter per request, clipped to 48,000 characters; unsaved drafts and approved chapters block (`test_unsaved_changes_block_requests_and_accepts`, `test_approved_chapter_blocks_requests_and_accepts`); stale replace (`test_replace_selection_goes_stale_when_passage_changes`) |
| Mock adapter for CI; Ollama smoke test when available; live cloud opt-in | `providers/mock.py` (deterministic, labelled "not AI"); `test_ai_live.py::test_ollama_smoke` (`-m ollama`, skipped here); `python -m pbs_core.live_check` (never run by tests) |

## Phase 03: what was built

**Core**
- Migration `0004_ai_jobs` adds these tables: `provider_config`, `model_info`, `task_route`, `model_price`, `cloud_consent`, `job`, `job_log`, `proposal`, `usage_record`. It also adds `usage_record` immutability triggers and a partial unique index on `chapter_revision.accepted_proposal_id`.
- `providers/`:
  - `egress.py`: the gate, the external-request counter and live cloud activity;
  - `base.py`: neutral types and error classification;
  - adapters `mock`, `ollama`, `openai_compat` (OpenAI, Groq, xAI), `anthropic_adapter` and `gemini`;
  - `registry.py`: permits, key lookup, capability checks.
- `security/secrets.py`: keyring / dev-file / memory / read-only stores.
- `jobs/`:
  - `prompts.py`: versioned templates, random-tag data envelope, brainstorm schema;
  - `runner.py`: claim, lease, recovery, cancel, bounded pool;
  - `execute.py`: build, call, stream progress, retry/backoff, one-transaction commit.
- `services/ai.py` covers privacy mode, providers, keys, test, models, routes, prices, consent, estimate, enqueue, jobs, proposals, accept/reject and usage. `services/costs.py` computes estimates and costs; it never invents a price.
- `api/routes_ai.py` adds 27 endpoints. The job runner starts and stops with the app.
- `live_check.py` is the opt-in real-provider check.

**UI**
- **AI settings** (replaces the "not implemented" page):
  - privacy mode, with a confirmation before allowing cloud and the count of internet requests;
  - providers with on-computer/cloud labels, key status, store/remove key, test connection, find models, models table with capability sources, add a model manually with a declared capability, turn off, remove;
  - default model per task, with temperature and max output;
  - prices with source and date.
- **AI assist** in the chapter editor:
  - task, model (default or explicit, labelled with where it runs), instruction, placement, max tokens;
  - an estimate shown before running;
  - an explanation when a request is blocked, with a one-click per-book consent when cloud is allowed;
  - a "save first" guard;
  - request status by stage, with Cancel and Retry;
  - a review pane: a proof-slip card with provenance, editable text, struck-through original for replacements, "Accept as a new revision" or Reject. Notes can only be dismissed.
- A banner says when suggestions are waiting.
- **AI jobs** status center: every job with stage, attempts, error, log, partial output, Cancel/Retry, and a usage and cost table with totals by currency.
- The privacy badge shows "Sending to …" during cloud calls.
- Navigation: AI jobs and AI settings are now live.

**Docs:**
- ADR-0004 (provider integration).
- As-built sections in SECURITY (§7b), ARCHITECTURE (§6.1, §7.1), DATA_MODEL (§2.3) and TEST_PLAN (§4.4).
- A README "Using AI" section and new `PBS_*` settings.

## Decisions taken in Phase 03 (need your validation)

| # | Decision | Why | Reversible? |
|---|---|---|---|
| P3-1 | Support **both** xAI Grok and Groq ("Grok" was ambiguous) | Both are cheap to add through the OpenAI-compatible SDK | Yes |
| P3-2 | Chat Completions for OpenAI, Groq and xAI (not the Responses API) | The one shape all three share; OpenAI still supports it; xAI calls it legacy | Yes; follow-up in ADR-0004 |
| P3-3 | Gemini via REST `generateContent` (legacy but supported), not the new Interactions API | Better-documented streaming and usage | Yes |
| P3-4 | `dev-file` key fallback (opt-in, warned), superseding SECURITY §3 "no plaintext file" | The Phase 03 brief asked for an explicit protected dev fallback | Yes |
| P3-5 | Ollama only on loopback; remote Ollama refused | A LAN server is not "local"; it has no allowlist entry | Yes, with consent rules |
| P3-6 | AI works only from the **saved** head; unsaved drafts block Ask and Accept | Provenance stays tied to an immutable revision, and a draft is never destroyed | Yes |
| P3-7 | Threads + SQLite claim instead of asyncio workers; single-step jobs (`job_step` deferred to Phase 06) | Simpler cooperative cancel with the sync SDKs | Yes |
| P3-8 | Stale proposals are computed when read; the "rebase" is "ask again" | No stored state to drift | Yes |
| P3-9 | No shipped prices; prices are per provider and model, entered by the author | "Do not guess" | Yes |
| P3-10 | The built-in test model is listed in dev/test only, labelled "not AI" | Lets the workflow be tried offline without misleading anyone | Yes |

## Known limitations (Phase 03, honest list)

1. **No real Ollama or cloud provider was exercised here.**
   - Ollama is not installed on this machine, and no API keys were used.
   - Adapters are tested against the documented wire formats, and the UI flow against a loopback Ollama stub.
   - Run `uv run pytest -m ollama` (with `PBS_OLLAMA_MODEL`) and `python -m pbs_core.live_check` to confirm against real services.
2. Facts not verifiable from the docs are listed in ADR-0004 ("Not verified"):
   - OpenAI Responses usage fields;
   - Gemini `RetryInfo` and pagination;
   - Groq streamed usage;
   - the xAI error format.
3. **The review pane has no word-level diff for "replace" suggestions.** It shows the struck-through original and the new text. Append and insert suggestions are pure additions.
4. Requests send **one chapter** (clipped to 48,000 characters). There is no cross-chapter or book-level context yet (Phases 05–06).
5. **Token estimates** use ~4 characters per token. They are labelled as estimates, and actual reported usage is recorded after each call.
6. Research is plain model knowledge with no web access, and the UI says so. Sourcing and citations arrive in Phase 04.
7. Cancelling a non-streamed Groq structured request takes effect after the response arrives, and the result is then discarded.
8. **The Windows credential store is used in dev runs** (`auto`). Tests and e2e use the in-memory store. The macOS Keychain is untested.
9. The `.claude/launch.json` preview needed two starts in the desktop browser pane.
10. My visual check left a "Built-in test model" provider, one job and one pending suggestion in the dev workspace (`.pbs-data`, git-ignored). Reject the suggestion or remove the provider in the app to tidy up.

## Phase 03: bugs found and fixed

- **Hypothesis found a Phase 02 serializer bug:** an attribute value ending in `\` escaped its closing quote. Backslashes are now entity-escaped, with a regression test.
- **Nested-transaction lock:** reading the privacy setting inside the request transaction deadlocked. It is now read in the same session.
- **The mock output was not deterministic:** the random envelope tag changed its hash.
- **E2E found that a job finishing in the background did not refresh the review pane.** The pane now invalidates when a job succeeds.
- **The instruction box inherited the 60vh editor height**, and a few labels were redundant (visual check).
- **Tests were order-dependent** on the process-wide egress counter. They now compare against a baseline.

## Phase 04 handoff

Preserve:
- the egress gate as the only network path (add allowlist entries, never bypass it);
- `registry.permit_for` and the per-project consent;
- prompts with data envelopes (`jobs/prompts.py`): extend `build()` with retrieved source chunks as **more envelopes**, never as instructions;
- proposals as the only way AI text reaches a revision;
- the unique index on `accepted_proposal_id`;
- the capability vocabulary;
- "unknown, not guessed" for prices.

Start Phase 04 with:
- the source library and chunk IDs that prompts can cite;
- dropping model-emitted citations that are not in the provided set (SECURITY §5.4);
- the prompt-injection fixture suite (§5.6) run through the mock adapter.

---

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

### Phase 11: Final acceptance testing and stabilisation (2026-11-23)
- Audited every PRD requirement against its tests (FEATURE_MATRIX), ran a full publishing simulation with per-format inspection, re-verified the Ubuntu deployment (including an isolated restore and a killed worker), measured NFR-4 for the first time, fixed the defects found, and wrote the five release documents.
- EPUBCheck could not be run: downloading it was refused by this session's permission settings.

### Phase 10: Ubuntu deployment and operations (2026-11-23)
- Built the Compose setup for Nginx Proxy Manager, operations scripts and end-to-end validation; ran them on Ubuntu 24.04.5 (containerised) behind NPM 2.17.1 with a real local model.

### Phase 09: Production hardening and web architecture (2026-11-23)
- Inspected the app first (ADR-0010 §2): no desktop shell existed; the desktop assumptions were the loopback-only bind, the per-launch token injected by the Vite proxy, the OS keyring and the in-request builds.
- Built as described in "Phase 09: what was built", in the same working tree as Phase 08 (both uncommitted).
- OWASP's Password Storage Cheat Sheet was read on 2026-11-23 for the scrypt parameters.
- Checked with the full test script, a real Docker build and Compose run over HTTPS, an upgrade of a copy of the dev workspace, and by hand in the desktop browser pane (setup, sign-in, Account) with a throwaway workspace.

### Phase 08: Advanced features (2026-11-23)
- Built as described in "Phase 08: what was built" on `phase/08-advanced`.
- OpenAI's audio API reference and guides were read on 2026-11-23 before the cloud engines were written (ADR-0009).
- Checked end to end with Playwright (series, canon edit, contradiction, resolution kept, passage link, French edition, language links, narration with no engine) and by hand in the desktop browser pane.

### Phase 07: Publishing (2026-11-22)
- Built as described in "Phase 07: what was built" on `phase/07-publishing`.
- The KDP help pages were fetched and read on 2026-11-22 before the rules were written (ADR-0008 lists them).
- Checked end to end with Playwright (build all formats, previews, covers, package, open the preflight report) and by hand in the desktop browser pane (package tab, preflight report, eBook cover). The first print PDF was also inspected as page images.

### Phase 06: Writing pipeline and reviews (2026-11-22)
- Built as described in "Phase 06: what was built" on `phase/06-writing`.
- Checked end to end with Playwright against the built-in test model: a three-chapter book drafted section by section with the review gate, paused and resumed, job history inspected, a locked chapter left untouched; quality checks and an editor action with a diff.
- Checked by hand in the desktop browser pane (Write and review page).

### Phase 05: Project planning (2026-11-22)
- Built as described in "Phase 05: what was built" on `phase/05-planning`.
- Open Library's search API was checked against its official docs before the adapter was written.
- Checked by hand in the desktop browser pane (Plan → Outline → the hand-written outline editor with a nested section and its tools), and end to end with Playwright against the built-in test model.

### Phase 04: Knowledge and evidence (2026-11-22)
- Built as described in "Phase 04: what was built" on `phase/04-knowledge`.
- Checked by hand in the desktop browser pane (book Sources page → search with highlights, locator and reasons), and end to end with Playwright against the built-in test model.

### Phase 03: AI providers and durable jobs (2026-11-22)
- Built as described in "Phase 03: what was built" on `phase/03-ai-jobs`.
- Provider endpoints were verified against the official docs by a research pass before the adapters were written.
- Checked by hand in the desktop browser pane (AI settings → built-in test model → AI assist → suggestion card), and end to end with Playwright against a loopback Ollama stub, including a hard Core crash mid-job.

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
