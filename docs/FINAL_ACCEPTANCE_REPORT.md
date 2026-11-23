# Final acceptance report

Personal Book Studio, Phase 11 (2026-11-23).

## Verdict: READY FOR PERSONAL USE, with conditions

Every final acceptance criterion passed on the test systems. Three conditions apply.

1. **Run EPUBCheck before submitting an EPUB to a store.** The studio's own EPUB checks pass, but the W3C
   validator could not be run here (KNOWN_ISSUES 1; command included).
2. **Run `DEPLOYMENT_VERIFICATION.md` §3 once on your own Ubuntu server.** The Ubuntu verification ran on
   Ubuntu 24.04.5 in a container with its own Docker Engine, not on a physical or cloud host.
3. **Commit the work.** Phases 08 to 11 exist only in the working tree.

| Final acceptance criterion | Result | Evidence |
|---|---|---|
| No known critical security or data-loss defect remains | **PASS** | KNOWN_ISSUES has no open item rated above Medium. The one high-severity operational defect found (truncated logs) is fixed and re-tested |
| Core book workflows execute successfully | **PASS** | Publishing simulation (`test_final_acceptance.py`); deployed end-to-end run on Ubuntu (DEPLOYMENT_VERIFICATION) |
| Imports preserve original source documents | **PASS** | SHA-256 of the stored original equals the upload (local and Ubuntu); original files identical after an isolated restore |
| AI edits require explicit user review | **PASS** | Suggestions stay pending; rejecting leaves the text byte-identical; accepting creates one revision; a second accept is refused. Tested locally with the test model and on Ubuntu with a real local model |
| Publishing exports pass format validation and content inspection | **PASS (EPUBCheck pending)** | DOCX, EPUB and PDF opened and inspected (per-format table below); preflight passes except the expected KDP minimum page count for a short test book. EPUBCheck BLOCKED |
| Data persists after restart | **PASS** | Restart, full container recreation, a reboot-like stop and start, three updates, a rollback, a killed worker: all revision hashes, assets and exports identical |
| Backup restoration verified | **PASS** | `restore.sh` in production (a later change removed, everything else identical) and into an **isolated** environment (identical fingerprints) |
| Authentication and deployment security checks pass | **PASS** | All 219 API operations need a session; CSRF on every write; only NPM exposed; no secrets in logs; HSTS and CSP through NPM |

## What was done

1. **Audit:** every PRD requirement and every function this prompt names was mapped to its evidence:
   `FEATURE_MATRIX.md`, 100 rows (70 PASS, 26 PARTIAL, 3 BLOCKED, 1 NOT IMPLEMENTED). A screen
   existing never counted as evidence.
2. **Publishing simulation:** `apps/studio-core/tests/test_final_acceptance.py`.
   - **Representative book:** three chapters, two tables, a diagram with alt text and caption, a Python
     code listing, inline and display math, citations with a bibliography, a footnote, a
     cross-reference, front matter (title, copyright, dedication, contents) and back matter (glossary,
     bibliography, index, about the author).
   - **Steps:** imported from a Markdown manuscript, edited by AI (one suggestion rejected, one
     approved), then exported and inspected.
3. **Ubuntu deployment verification:**
   - Compose configuration, health, migrations, exposure, logs and authentication;
   - a full end-to-end run with a real local model;
   - the worker killed mid-job;
   - a real backup restored into an isolated environment;
   - update, update with a cron-style log, and rollback.
4. **Performance (NFR-4, first measurement):** a book of 100 chapters, 500 images and 10,000 source chunks.
5. **Stabilisation:** the defects below were fixed, and the full test suite was re-run after the fixes.

## Publishing simulation: results per format

All checks are automated in `test_final_acceptance.py` and passed.

| Inspection | DOCX | EPUB | PDF |
|---|---|---|---|
| No missing chapters (three, in order) | PASS (Heading 1 order) | PASS (navigation lists all three) | PASS (text) |
| Front and back matter, bibliography, footnote | PASS | PASS | PASS |
| Images not broken | PASS (one picture; alt text in `descr`) | PASS (every `<img>` resolves inside the package) | PASS (image object present) |
| References correct | PASS ("Torque 2019, p. 3"; "Jane Torque" in the bibliography) | PASS (same; every internal link and fragment resolves) | PASS (same) |
| Formatting not lost | PASS (2 tables; code, equation and caption styles) | PASS (2 tables; MathML with `mfrac`) | PASS (6 × 9 in pages, 19 pages; fonts embedded) |
| No duplicated passages (one sentence per chapter appears exactly once) | PASS | PASS | PASS |
| Technical content unaltered | PASS (every code line verbatim) | PASS (code verbatim in `<pre>`) | PASS (code verbatim in the text layer) |
| Approved AI edit present; replaced text gone | PASS | PASS | PASS |
| Fidelity line | "degraded": equations kept as LaTeX source (documented) | "ok" | "degraded": links printed as addresses (documented) |
| Preflight | Package, opens, alt text: pass; equations and TOC: manual | Container, metadata, manifest, navigation, XHTML, links, alt text, accessibility: pass; **EPUBCheck: unavailable**; Kindle Previewer: manual | Page size, margins, bleed, fonts, image resolution, language, bookmarks, encryption, size, blank pages, text size, overflow, equations: pass; **page count: fail (19 < KDP's 24 minimum; expected for a short test book)**; links: warn; PDF standard: manual |

The same flow on Ubuntu, with a DOCX manuscript and a real local model, produced DOCX (39,750 bytes),
EPUB (80,036 bytes) and PDF (37,029 bytes, 7 pages). Each was checked by file signature and stayed
identical across restart, recreation and restore.

**Not claimed:** compliance with KDP or any store's requirements. The studio's preflight is a helper. Use
the store's previewer (and EPUBCheck) before publishing.

## Tests executed

| Suite | Result |
|---|---|
| Core (pytest) | **308 passed, 1 skipped** (the skip is a live Ollama test without a local Ollama) |
| UI (Vitest + axe) | **51 passed** |
| Browser (Playwright + axe) | **19 passed** |
| Lint, format, strict types, import contracts, license gate, production build | all clean |
| Repeated browser runs after the flaky-test fixes | 18/18 and 8/8 on the affected specs |
| Ubuntu deployment harness | all sections passed (DEPLOYMENT_VERIFICATION §2) |
| Performance | library 85 ms, chapter tree 46 ms, full-text search 41 ms (median), EPUB export 2.7 s; targets under 2 s, under 300 ms and under 60 s. API timings on the dev machine; editor keystroke latency not measured |

The final run's exact output is recorded in BUILD_STATE (Phase 11 evidence). One earlier run stopped on a Windows socket-buffer error, which comes from machine load, not the studio (KNOWN_ISSUES 19); the re-run passed.

## Bugs fixed in Phase 11

1. **Operations, high:** `update.sh` and `run_e2e.sh` truncated a log file their output was redirected
   to (`tee /dev/stderr`). Fixed with `backup.sh --path-file`, and re-tested with an appended log.
2. **Test reliability, medium:** three intermittent browser-test failures. They came from two races in
   the tests themselves (an AI panel toggled before render; navigating before a provider was saved), not
   from the app. Fixed with shared helpers, and re-run repeatedly.
3. **Operations, low:** `restore.sh` could not restore onto a fresh server; isolated rehearsals were not
   possible. Fixed (empty-folder restore; `PBS_PROJECT_NAME`).
4. **Documentation:** BUILD_STATE lacked the Phase 10 evidence that DEPLOYMENT.md cited; it is added.

No application security or data-loss defect was found.

## Startup and shutdown

On the server, from `/opt/book-studio`:

```sh
sudo docker compose -f deploy/compose.yaml --env-file deploy/.env up -d      # start (add --profile local-ai for the Ollama container)
sudo docker compose -f deploy/compose.yaml --env-file deploy/.env stop       # stop (keeps everything)
sudo docker compose -f deploy/compose.yaml --env-file deploy/.env restart app worker
sudo deploy/scripts/validate.sh --url https://books.example.com              # check
```

Never add `-v` to a `down` you type yourself; the data lives in host folders, but other stacks' volumes
might not. First install, updates and rollback: `DEPLOYMENT.md` and `OPERATIONS.md`.

**Application URL:** `https://<PBS_DOMAIN>`, through your Nginx Proxy Manager proxy host to
`http://book-studio-app:8765` (DEPLOYMENT §3). For development without Docker: `scripts/dev.ps1`, then
http://127.0.0.1:5173.

## Backup and restore

- **Back up:** `sudo deploy/scripts/backup.sh` (nightly: `--label nightly --keep 14` from cron). Each
  archive is verified, checksummed and kept root-only in `/srv/book-studio/backups`. Keep the master key
  (`/srv/book-studio/secrets/pbs_master_key`) separately, and copy backups off the server.
- **Restore:** `sudo deploy/scripts/restore.sh <archive>`. It verifies first and moves the current data
  aside, never deleting it. On a new server: install, copy the master key and the archive, then restore
  (OPERATIONS §4).

## AI provider configuration

AI settings → **Add provider**:
- **Ollama**: `http://ollama:11434` for the container; `http://host.docker.internal:11434` for Ollama on
  the server; or `http://<address>:11434` for a trusted computer named in `PBS_LOCAL_AI_HOSTS`.
- **Cloud** (OpenAI, Anthropic, Gemini, Groq, xAI): enter the key; it is stored encrypted.

Then **Test connection** and **Find models**. Cloud use needs **Cloud allowed** and per-book consent;
`PBS_ALLOW_CLOUD=false` turns cloud off server-wide. Details: DEPLOYMENT §5, USER_GUIDE.

## Recommended next improvements (in order)

1. Run EPUBCheck on a real export, and install Java with EPUBCheck in the image or on the server so
   preflight reports it automatically.
2. Verify on a physical or cloud Ubuntu server with Let's Encrypt and VPN access (DEPLOYMENT_VERIFICATION
   §3).
3. EPUB import (convert spine documents through the existing HTML importer).
4. Phase 08 data in per-book backups.
5. Imports as background tasks.
6. Off-site, encrypted backups; an image vulnerability scan; a pinned Ollama image.
7. Permanent, confirmed book deletion; per-paragraph AI-origin tracking for the disclosure checklist.
8. Real-key smoke tests for cloud providers and real speech engines; a manual screen-reader audit.

## Related documents

`FEATURE_MATRIX.md` · `DEPLOYMENT_VERIFICATION.md` · `KNOWN_ISSUES.md` · `USER_GUIDE.md` ·
`DEPLOYMENT.md` · `OPERATIONS.md` · `BUILD_STATE.md`
