# Personal Book Studio — Security & Privacy

Status: Draft v0.1 (Phase 00). Scope: single user, single device. The user is trusted. Everything that enters from outside (files, web pages, model output, other local processes, other browser tabs) is not.

## 1. Assets to protect

| Asset | Why it matters |
|---|---|
| Manuscripts, revisions, originals | The user's IP. Loss or leak is the worst outcome |
| Provider API keys | Financial exposure, account abuse |
| Research sources and interview answers | May contain personal data of third parties |
| Integrity of citations and provenance | Fabricated evidence harms the author's reputation |
| Disk outside the workspace | Core must never read or write arbitrary paths |

## 2. Threat model (STRIDE-lite)

| Threat | Vector | Control |
|---|---|---|
| **Drive-by local API abuse** (CSRF, DNS rebinding) | A malicious website the user visits sends requests to `127.0.0.1:<port>` | Bind only to `127.0.0.1`. **Host allowlist** (`127.0.0.1:<port>`, `localhost:<port>`). **Origin check** on every non-GET (must equal the UI origin or be absent for the Tauri custom protocol). **Session token** required as the `X-PBS-Token` header on every `/api` call. The token is 256-bit random, generated each launch and written to `runtime/session.token` with a user-only ACL. In dev, the Vite proxy injects it; under Tauri, the shell passes it to the webview. Custom headers force a CORS preflight, which Core rejects (no CORS headers are emitted at all) |
| Other local users/processes | Reading the token or DB | Workspace under the user profile. Token file ACL is user-only (Windows: `icacls` with a fixed argument list, removing inherited ACEs and granting only the current user; POSIX: 0600). Single-user OS assumption documented |
| Path traversal | Import names, ZIP entries, export names, API params | Paths come from IDs only. `safe_join()` rejects absolute paths, `..`, drive and UNC prefixes, `:` (NTFS ADS), reserved names (`CON, PRN, AUX, NUL, COM1–9, LPT1–9`), trailing dots/spaces, and symlink or junction escapes (resolve, then verify the prefix) |
| Archive attacks | DOCX/EPUB/backup ZIP bombs, traversal | Max entries (10k), max total uncompressed (default 2 GiB), max ratio (100:1) per entry, streaming size enforcement, no symlink entries, `safe_join` per entry |
| XML attacks | DOCX/EPUB/HTML imports (XXE, billion laughs) | `defusedxml` for all XML parsing. `lxml` only with `resolve_entities=False, no_network=True` |
| XSS / script injection | Imported HTML, model output, Markdown | BookMD raw HTML disabled. All HTML produced by Core goes through the native renderer (escapes text). Imported HTML is converted to BDM, never passed through. Any HTML string shown in the UI is sanitized with **nh3** (ammonia) using an allowlist. The UI never uses `dangerouslySetInnerHTML` except through one audited `<SanitizedHtml>` component. Strict CSP in Tauri and the dev server (`default-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'`) |
| Unsafe links | `javascript:`, `data:` in links | Link scheme allowlist in the parser (`http, https, mailto, #, pbs:`). Others are rendered inert and flagged |
| Oversized / encrypted files | DoS, crashes | Upload cap (default 200 MB, configurable). Encrypted PDF/DOCX detected and reported, never brute-forced. Per-importer timeouts |
| **Prompt injection** | Knowledge sources, imported text, web results, previous model output | See §5 |
| Data exfiltration | Model output tricks the app into fetching URLs; cloud call in local-only mode | The model has **no tools** that touch the network or filesystem. The app never auto-fetches URLs appearing in model output. Egress gate (§4) |
| Secret leakage | Logs, exceptions, exports, backups, Git | §3 + redaction filter + tests that grep artifacts for planted canary keys |
| Repudiation / provenance tampering | AI text disguised as human | Origin recorded by Core, not the client. Revisions immutable (triggers). AI-origin revisions require `accepted_proposal_id` |
| Supply chain | Malicious or abandoned packages | Lockfiles (`uv.lock`, `pnpm-lock.yaml`) committed. `pnpm` `minimumReleaseAge` / audit, `pip-audit`, license gate (§7). Few dependencies. Renovate-style manual review |
| Running external tools | Pandoc / EPUBCheck / Calibre argument injection | `subprocess.run(list, shell=False)`. Absolute tool path. Inputs are temp files with generated names. Timeouts. Pandoc run with `--sandbox` (no filesystem/network access by readers/writers) |

## 3. Credentials

- Stored with the Python **`keyring`** library, backed by Windows Credential Manager on Windows and macOS Keychain on macOS (Linux: Secret Service, when present). Service name `PersonalBookStudio`, account `provider:<provider_config_id>`.
- The DB stores only `credential_ref`. **Never** the secret, a hash of it, or a prefix of it.
- Keys are read just in time for each call and kept only in local variables. They are never included in Pydantic response models (`SecretStr`, excluded from serialization), and never returned by the API after entry (the UI shows "•••• set", updated date).
- **Fallback when no keyring backend is available:** the user may set `PBS_<PROVIDER>_API_KEY` environment variables for the session. The UI then shows a persistent "insecure key source: environment" warning. PBS never writes the key to disk. No plaintext file fallback.
- Backups, exports, publish packages, logs and the Activity log never include credentials. Tests plant a canary key and scan every produced artifact.

## 4. Network egress and privacy modes

- **Modes:** `local_only` (default on first run) and `cloud_allowed`. The UI shows the mode at all times. When cloud is allowed, an "outbound activity" indicator shows the provider name during each call.
- **Egress gate:** every outbound request goes through `providers/egress.py`. Rules:
  1. In `local_only`, any request whose resolved host is not loopback raises `EgressBlocked` **before** connecting. No retry, no fallback to another provider, and the job fails with an explicit message.
  2. In `cloud_allowed`, a request needs (a) an enabled provider config, (b) per-project consent ("This project may send content to: OpenAI"), recorded with timestamp, (c) a host from that provider's allowlist.
  3. Local providers (Ollama) count as local only when the configured host resolves to loopback.
- **No telemetry, no update checks, no font/CDN fetches.** The UI bundles all fonts and assets. Vite build output has no external URLs (checked in CI).
- **Verification:** an integration test installs a socket guard (patching `socket.create_connection` / `getaddrinfo`) and runs the full acceptance scenario in `local_only` with the mock and Ollama-stub adapters. It asserts zero non-loopback connection attempts.

## 5. Prompt-injection isolation

1. **Typed prompt assembly.** Prompts are built from `TrustedInstruction` parts (app-authored templates, versioned in the repo) and `UntrustedContent` parts (sources, manuscript text, user-imported docs, web results, prior model output). Untrusted parts are wrapped in clearly delimited, randomly-tagged data envelopes (`<pbs:data id="r4f9…">…</pbs:data id="r4f9…">`). The instructions state that envelope content is reference material, not instructions.
2. **No tool use from content.** The application does not give models tools that read files, browse, or modify data. Structured outputs (JSON) are validated against Pydantic schemas. Output fields cannot name arbitrary actions, only fill fixed slots.
3. **Output is a proposal.** Even a fully compromised model output can only produce a pending proposal that the user reviews as a diff.
4. **Citations must resolve.** Model-emitted citation keys or chunk IDs that are not in the provided set are dropped and flagged "unverified". Invented URLs and DOIs are rejected (only IDs from the ledger are accepted).
5. **Content sanitization.** Imported HTML and web pages are reduced to text + structure before indexing. Hidden text (CSS-hidden, zero-width, white-on-white where detectable) is kept but marked, so users can inspect it.
6. **Test fixtures** include malicious documents ("ignore previous instructions and…", fake system tags, envelope-escape attempts, instructions to cite fake sources). Tests assert no state change outside the proposal and no new citations.

## 6. Data handling

- Manuscript text is **not written to logs** (IDs, lengths and hashes only). Debug logging that includes content is opt-in, time-limited, and bannered.
- Deleting is archiving by default. Purge is explicit, offers a backup first, and removes files and rows for that project only.
- Temp files go to `<workspace>/runtime/tmp/<job_id>/` and are cleaned on completion and at startup.
- Third-party personal data in interviews and sources: the UI reminds the user about consent when the interview workspace is used (Phase 04). PBS never transmits it except to the providers the user explicitly selects.

## 7. Repository hygiene (public GitHub repo)

The remote `github.com/fpokrzywa/book_studio` is **public**. Therefore:
- `.gitignore` covers `.pbs-data/`, `**/*.db`, `**/*.db-wal`, `**/*.db-shm`, `.env*`, `runtime/`, `logs/`, `exports/`, `backups/`, `*.pbsbak.zip`, `node_modules/`, `.venv/`, `dist/`, `target/`.
- Fixtures are synthetic or public-domain only (e.g., text the project writes itself, or Project Gutenberg public-domain text with attribution). Never the user's real manuscripts.
- Pre-commit hook: `gitleaks` secret scan (optional if not installed; CI runs it).
- License gate in CI: fail on AGPL/GPL/SSPL in shipped runtime dependencies unless an ADR allows it. External, user-installed tools (Pandoc GPL, Calibre GPL) are invoked as separate processes and not bundled. That is documented.

## 7a. Phase 02 controls as built

- **Uploads:** read in 1 MB chunks with a hard cap (`PBS_MAX_UPLOAD_MB`, default 200; images 25 MB; backups `PBS_MAX_BACKUP_MB`, default 4096). Over the cap → 413 `payload_too_large`.
- **Archives (DOCX, backups):** `security/archive.py` inspects the central directory before anything is opened: entry count, declared and actual sizes (reads are size-capped), compression ratio (zip bombs), unsafe names (absolute, `..`, drive letters, backslashes, reserved names, `:`), symlinks, and encryption flags. DOCX XML parts with `<!DOCTYPE`/`<!ENTITY` are rejected (XXE / entity expansion) before mammoth runs.
- **Format sniffing** by magic bytes first: old `.doc` and encrypted Office files (OLE container) are refused with guidance; encrypted PDFs are refused unless they open with an empty password.
- **HTML imports:** standard-library parser (no DTD or entities, no network). Only known elements are mapped. `script/style/iframe/object/embed/form/svg/canvas/…` are dropped and reported. No attribute is ever copied through, so `on*` handlers cannot survive. `javascript:`/`data:` links are removed. Remote images are not downloaded (privacy); `data:` images must sniff as PNG/JPEG/GIF/WebP.
- **Images:** raster only (SVG refused because it can carry script). Served with `X-Content-Type-Options: nosniff` and a `sandbox` CSP. The same headers apply to export, backup and original downloads.
- **Preview/HTML export:** escaped renderer → nh3 allowlist (HTML + MathML). The UI inserts HTML in exactly one audited component. External images render as a labelled placeholder (no request). The HTML export carries a CSP that blocks scripts and network loads.
- **Originals:** stored before parsing, content-addressed, read-only on disk, and immutable in the DB. A failed import keeps the original.
- **Restore:** manifest/1 schema validation, a SHA-256 and size check for every file, no unlisted files, a refusal for newer schema revisions, and a NEW project with new IDs (never overwrites). Files written for a failed restore are removed.

## 7b. Phase 03 controls as built (details: ADR-0004)

- **Egress gate** (`providers/egress.py`): every provider request is re-checked in an httpx2 request hook. Loopback always passes. Anything else needs `cloud_allowed` + this project's consent + the provider's allowlisted host + https. No redirects, no environment proxies. `external_requests()` counts what reached the internet, and the AI settings page shows it. A pytest socket guard plus egress-counter assertions prove zero non-loopback traffic in local-only runs.
- **No fallback:** a request runs on the provider and model it names, or on that task's configured route, or fails with `model_not_chosen`. Revoking consent fails queued cloud jobs with `egress_blocked` before anything is sent.
- **Ollama must be on this computer:** non-loopback Ollama URLs are refused at configuration time and by the gate.
- **Keys:** OS credential store by default. The `dev-file` fallback (development only) is explicit opt-in (`PBS_SECRET_BACKEND=dev-file`), user-only ACL, and a warning in the UI. This **supersedes** §3's "no plaintext file fallback" for development machines without a keyring. The environment-variable source is read-only and also warned about. Keys are `SecretStr`, never returned, never logged. The canary test scans the DB, WAL, logs, backup ZIP and exports.
- **Prompt assembly:** manuscript text sits in a random-tag `<pbs-data-…>` envelope, and the system prompt says envelope content is never instructions. Models have no tools. Structured output is schema-validated. Output is only ever a proposal.
- **Scope:** one chapter of one project per request, clipped to 48,000 characters.

## 7c. Phase 04 controls as built (details: ADR-0005)

- **Source text is untrusted data.**
  - Imports reuse the Phase 02 safe importers (archive, XXE, encrypted and scanned checks; HTML reduced to structure with script, handlers and `javascript:` links dropped).
  - Every passage, interview answer and writing sample is sent in its own random-tag envelope, and any envelope-like text inside it is neutralised.
  - The system prompt forbids following embedded instructions and inventing titles, authors, pages, URLs or DOIs.
- **Citations can only point at what was sent.**
  - Labels the model emits for passages it was not given are dropped and reported.
  - Cited sentences are checked against the passage and flagged when not located.
  - BookMD keys come from the source record, never from model text.
- **Search output is plain text segments**, not HTML; the UI renders source text as text. FTS query syntax cannot be injected because user words are quoted tokens.
- **Scope.**
  - A generation can use only enabled, indexed, not-removed sources of the book's own libraries or shared libraries it opted into.
  - Disabling a source takes effect at the next run.
  - Author-added evidence is refused for passages outside the book's sources.
- **The author's own words.**
  - Interview answers are immutable (DB triggers; edits are new versions).
  - Voice samples require an explicit rights confirmation (API plus DB CHECK).
  - Prompts forbid inventing personal experiences.
- **Tests:** a malicious source (`fixtures/knowledge/malicious-source.html`) and a plain-text source with forged envelopes are run through the test model, including a simulated compromised model that repeats the injected text. Assertions:
  - the injected citation is dropped;
  - no invented key is cited;
  - nothing outside the proposal changes (chapter, privacy mode, providers, sources);
  - the preview escapes raw HTML.

## 8. Security acceptance checks by phase

| Phase | Must pass |
|---|---|
| 01 | Loopback bind; Host/Origin/token guard tests (missing token → 401, bad Host → 421/400, cross-origin POST → 403); `safe_join` unit tests incl. Windows edge cases; redaction filter tests; no external network in the test suite (socket guard) |
| 02 | ZIP bomb / traversal / XXE / encrypted-file fixtures; HTML import XSS fixtures; backup restore never overwrites |
| 03 | Keyring storage; canary-key artifact scan; local-only zero-egress test; no silent fallback test |
| 04–06 | Prompt-injection fixture suite; citation-resolution enforcement |
| 07 | Export/package artifact scan for secrets and absolute local paths |
| 09 | Full audit → `docs/SECURITY_AUDIT.md` |
| 10 | Sidecar token handoff; port only on loopback; CSP in Tauri config; signed/unsigned build disclosure |
