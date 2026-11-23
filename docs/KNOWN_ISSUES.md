# Known issues and limitations

Status at the end of Phase 11 (2026-11-23). No known critical security or data-loss defect remains open.
There are 6 unverified items, 7 medium and 7 low.
Each item gives its severity, its effect and what to do about it.

| Severity | Meaning |
|---|---|
| **High** | Affects a core workflow or a guarantee. |
| **Medium** | A missing part of a feature. |
| **Low** | Cosmetic, or a documentation gap. |
| **Unverified** | Not run in this environment; exact commands are given. |

## Open items

| # | Severity | Issue | Effect | Workaround / next step |
|---|---|---|---|---|
| 1 | Unverified | **EPUB files were not checked with EPUBCheck.** It is not installed, and this session's permission settings refused to download it. | The studio's own EPUB checks pass (container, metadata, manifest, navigation, well-formed XHTML, internal links, alt text, accessibility metadata), but the W3C validator was not run. | Run it yourself; see "Commands for checks not run here" |
| 2 | Unverified | **No physical or cloud Ubuntu server was used.** The deployment ran on Ubuntu 24.04.5 inside a privileged container with its own Docker Engine. | Kernel, systemd, `ufw` and real network behaviour are untested. | Follow DEPLOYMENT_VERIFICATION.md on your server |
| 3 | Unverified | **Let's Encrypt, DNS challenges and VPN access** were not tested (a private test CA was used). | Certificate issuance is untested here. | NPM's own Let's Encrypt; check with `validate.sh --url` |
| 4 | Unverified | **Cloud AI providers were never called with real keys.** Only offline contract tests against recorded request formats were run. | A provider API change would show up only in use. | Add a key, then **Test connection** and **Find models** in AI settings |
| 5 | Unverified | **No real speech or transcription engine** was run (eSpeak NG, Piper, Whisper, OpenAI audio). | Narration audio and transcripts are untested with real engines. Graceful degradation is tested. | Build with `PBS_WITH_ESPEAK=1`, or allow OpenAI audio |
| 6 | Unverified | Ollama **installed natively on the host** (`host.docker.internal`) and macOS were not tested. | — | DEPLOYMENT §5 |
| 7 | Medium | **EPUB import is not implemented** (DOCX, Markdown, text, HTML and text PDF are). | Existing EPUB books cannot be brought in directly. | Convert to DOCX or Markdown first (for example with Calibre or Pandoc). Recommended next feature |
| 8 | Medium | **Imports run inside the web request**, not in the background worker. | A very large import keeps that one request busy; NPM's long timeouts (DEPLOYMENT §3.2) cover it. | Keep uploads under the 200 MB limit |
| 9 | Medium | **Per-book backups omit Phase 08 data** (series canon, continuity decisions, edition links, narration audio, recordings and transcripts). | Restoring one book from its ZIP loses those links. | Use the whole-studio backup (`backup.sh`), which includes everything (verified by restore) |
| 10 | Medium | **No permanent book deletion.** Archive is the only removal. | Archived books stay in the database and backups. | By design for now; deletion needs a confirmed, audited flow |
| 11 | Medium | **AI origin is tracked per revision, not per paragraph.** | The KDP AI-disclosure checklist counts AI revisions, not passages. | Label revisions; review the checklist by hand |
| 12 | Medium | **DOCX keeps equations as LaTeX text; PDF prints link addresses instead of live links** (reported as "degraded" in each export's fidelity line). | Word users see `\frac{…}` source; PDF links are not clickable. | Edit equations in Word if needed |
| 13 | Medium | No licensed market-data source, no semantic search, no image-generation provider; covers are RGB only, with no hardcover. | Research brainstorming is labelled heuristic; search is word-based. | — |
| 14 | Low | Narrow, English-centric continuity and style rules (pronoun-only sentences are not linked to a character). | Some contradictions are missed. | The check is a helper; read the chapters |
| 15 | Low | Remote Ollama providers are labelled "Ollama (local)" and say "running locally". | Cosmetic. | — |
| 16 | Low | Accessibility is checked automatically (axe, keyboard-only flows), with no manual screen-reader audit. | Some issues only a person finds may remain. | — |
| 17 | Low | Not covered by any test: bounded job concurrency, log rotation, the SQLite durability settings, and the "sending to cloud" indicator. | Implemented, unproven by tests. | — |
| 18 | Low | `ollama/ollama` defaults to the `latest` tag and no image vulnerability scan was run. | Updates can change Ollama's behaviour. | Set `PBS_OLLAMA_TAG`; scan images in CI |
| 19 | Low | On this Windows machine, `WinError 10055` (no socket buffer space) stopped 2 of the last 7 full test runs, at one random test each time, under heavy load (Docker and nested Docker running). The test process holds about 2 sockets throughout, so this is not a leak. | A rerun passes. | Re-run; it is the machine, not the studio |
| 20 | Low | Phases 08 to 11 are **not committed**. The deploy scripts' executable bit may not be recorded by Git on Windows. | Lost work if the folder is lost. `sudo deploy/scripts/…` needs `bash` in front if the mode is missing. | Commit, then `git update-index --chmod=+x deploy/scripts/*.sh deploy/validation/run_e2e.sh` |

## Fixed in Phase 11

| Severity | Defect | Fix |
|---|---|---|
| High (operations) | `update.sh` and `run_e2e.sh` used `tee /dev/stderr`. When their output was redirected to a file (cron, `>> log 2>&1`), that reopened and **truncated the log**, losing earlier lines and writing NUL bytes. | `backup.sh --path-file`; callers no longer tee. Regression check on Ubuntu: the appended log keeps its first line and has no NUL bytes |
| Medium (test reliability) | Three browser tests failed intermittently (one or two in each full run). The cause was two test races: the AI panel was checked before the page rendered, which closed a panel stored as open; and the test navigated away before "Add provider" had been saved. | Shared helpers `openAiPanel` and `addMockProvider`, which wait for the real state. Repeated runs pass (18/18 and 8/8 on the affected specs) |
| Low | `restore.sh` could not restore onto a fresh server (it expected an existing data folder). | Restores into an empty folder; used for the isolated restore |
| Low | No way to run a second, isolated copy for restore rehearsals. | `PBS_PROJECT_NAME` in `deploy/.env` |

## Commands for checks not run here

EPUBCheck (needs Java). Set `V` to the latest version listed at
https://github.com/w3c/epubcheck/releases (without the leading "v"), and put the EPUB exported from
**Publish** in the current folder:

```sh
V=<version>   # for example the number shown on the releases page
docker run --rm -e V="$V" -v "$PWD:/work" eclipse-temurin:21-jre bash -c   'cd /tmp && curl -fsSLO "https://github.com/w3c/epubcheck/releases/download/v$V/epubcheck-$V.zip"    && apt-get -qq update && apt-get -qq install -y unzip >/dev/null && unzip -q "epubcheck-$V.zip"    && java -jar "epubcheck-$V/epubcheck.jar" "/work/Your Book.epub"'
```

The studio reports EPUBCheck automatically when `java` and an `epubcheck` command are on the server's
PATH.

Ubuntu, Nginx Proxy Manager, HTTPS and recovery on your own server: `docs/DEPLOYMENT_VERIFICATION.md`.
