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

## 7d. Phase 05 controls as built (details: ADR-0006)

- **Research egress.**
  - Open Library is the only network research source. It is off by default and needs `cloud_allowed`.
  - Its traffic goes through the egress gate (allowlist `openlibrary.org`).
  - It sends only the words the author typed, with a generic User-Agent and no personal details.
  - Every attempt, including blocked and failed ones, is recorded in `research_query`. Failures return an explicit 409 and add nothing.
- **No fabricated market data.**
  - AI brainstorms are stripped of sales, ranking, demand, competition and search-volume statements, and the removal is flagged.
  - DB CHECKs keep metrics to provider rows only, and keep "measured" findings tied to a named source.
  - Prompts state that no market data exists.
- **Planning text is untrusted data.** Brief fields and findings are passed to the model in random-tag envelopes, like all other untrusted material.
- **Spending.**
  - The budget cap is enforced before a run (upper bound) and during it (actual cost).
  - An unknown cost while a cap is set stops the run.
  - Bulk drafting needs an approved, applied outline. Its output is only ever proposals.

## 7e. Phase 06 controls as built (details: ADR-0007)

- **AI never overwrites the manuscript.**
  - Section drafts are stored on the draft plan.
  - A chapter changes only when the author accepts the single assembled suggestion.
  - Locked or approved chapters are never drafted, and suggestions for them cannot be applied.
- **Untrusted material stays data.** Brief, outline, earlier text, summaries, continuity notes, style guide and passages go to the model in random-tag envelopes. AI-extracted continuity notes are labelled unconfirmed until the author confirms them.
- **Protected content.** Code and math in a selection are replaced by placeholders and restored byte for byte. A reply that alters them is discarded.
- **No code execution.** Code checks parse Python and JSON only, run only when the author allows them for that book, and never execute code.
- **No false assurance.**
  - Quality checks and AI reviews say they are not proof of correctness.
  - AI review findings are kept only if they quote the chapter.
  - The originality report states its local scope and that no match is not proof of originality.
- **Spending.** Every section job counts against the run's budget cap. A stopped run cancels its plans.

## 7f. Phase 07 controls as built (details: ADR-0008)

- **Nothing is published or uploaded.** The package is a local folder and a ZIP, and its manifest says `auto_publish: false`. Preflight never contacts KDP or any web page.
- **No fabricated legal or identity data.** PBS writes no copyright notice and generates no ISBN; an ISBN with an invalid check digit is refused. Category suggestions are marked unverified, and metadata checks block promotional claims.
- **Exported HTML is inert.** It has a strict Content-Security-Policy and no scripts; images are embedded. It is served with `sandbox`, and the in-app reading preview is a `sandbox=""` iframe.
- **Cover rights.** Artwork needs the author's rights confirmation (source, license, confirmed). No image generation provider exists, and lettering is typography.
- **Code is never executed** (ADR-0007), and EPUBCheck runs only if the author installed it.
- **Files are written with `safe_join`** under the project's workspace folder. Package file downloads are limited to names in the package manifest.

## 7g. Phase 08 controls as built (details: ADR-0009)

- **Cloud audio uses the same gate as text.** OpenAI speech and transcription go through `gated_client` with a permit from `registry.permit_for`: cloud mode, the book's consent for that provider, and a key from the OS credential store. The service checks the permit **before** building a request and returns 409 with the reason; nothing is sent. A test proves that in local-only mode the egress counter and the mock transport see no request.
- **Opt-in engines only.** Narration is off per book until the author turns it on and picks an engine. Transcription runs only with the engine the author picks. Local engines run only if the author installed them. The built-in test engines exist only in dev and test (`env != "prod"`) and label their output as silence or "not real speech".
- **Subprocesses** (espeak-ng, piper, whisper) get an argument list (no shell), a private temporary folder, the text on stdin, and a timeout. Their output is read from that folder only.
- **Recordings are the author's.** Import requires a rights confirmation and real audio (magic bytes). The file is stored read-only, content-addressed. Transcript text and timestamps are immutable (database trigger). Quotations are copied verbatim with timestamps, and PBS never writes or edits speech text.
- **Canon is the author's.** AI and imported notes stay "suggested" until approved, with provenance. Continuity review reads chapters and never writes them. Translation reads an approved source revision and writes only a proposal on the edition's chapter. Protected content (code, math, citations, links) is masked, and a reply that alters it is discarded.
- **No invented costs or compliance.** Audio cost comes only from a price the author enters (otherwise "unknown"). Exports state the AI-voice disclosure and that they are not checked against ACX/Audible/KDP audiobook rules.
- **Downloads are confined.** Audio export names must match a strict pattern, and every file path goes through `safe_join`.

## 7h. Phase 09 controls as built (details: ADR-0010)

Phase 09 turns the studio into a self-hosted web application, so the "drive-by local API abuse" and
"other local users" rows of §2 are now covered by these controls instead of the per-launch token:

- **Authentication:** one owner account per studio. Passwords are scrypt hashes (n=2^17, r=8, p=1), at
  least 12 characters. First account only with the one-time setup code from `runtime/setup-code.txt`
  (mode 0600, never logged) or the server command line. Unknown usernames cost the same time as wrong
  passwords. 5 failed sign-ins in 15 minutes per address or username means a wait (HTTP 429).
- **Sessions:** 256-bit random token in an `HttpOnly`, `SameSite=Strict`, `Path=/` cookie, `Secure` with
  the `__Host-` prefix on https. Only SHA-256 hashes are stored. Idle 12 h and absolute 14 days
  (configurable). Password change ends other sessions; server reset ends all.
- **Authorization:** deny by default. The guard rejects every `/api` request without a session except
  `auth/state`, `auth/login` and `auth/setup`; a test calls all 219 API operations unauthenticated.
- **CSRF:** per-session token in `X-PBS-CSRF` on every POST/PUT/PATCH/DELETE (tested on every such
  route), plus Origin, `Sec-Fetch-Site` and SameSite checks. No CORS headers.
- **Headers:** CSP (`default-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'`…),
  `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, COOP/CORP, Permissions-Policy,
  HSTS on https. Exported HTML keeps its own sandbox CSP.
- **Requests and files:** bodies over the upload limit are refused before they are read (Content-Length
  and streamed). File endpoints still take IDs, never paths; the UI files are served through
  `safe_join` from the build folder only; uploads are typed by content (tests for both).
- **Credentials on a server:** AES-256-GCM in `runtime/secrets.enc.json`; master key from a Docker
  secret outside the data volume; wrong key fails closed; no keyring fallback on a server.
- **Network:** only the proxy publishes a port, bound to 127.0.0.1 unless the operator chooses an
  address (Docker-published ports bypass `ufw`). Core, worker and Ollama are on Docker networks; Ollama's
  is internal (no internet). Core and the worker run as a non-root user with a read-only root
  filesystem; every container drops all capabilities (the proxy keeps only `NET_BIND_SERVICE`) and sets
  `no-new-privileges`. Core trusts `X-Forwarded-*` only from the proxy address.
- **Local-only mode** is unchanged and still fails closed; operator-named private model hosts
  (`PBS_LOCAL_AI_HOSTS`) are the only additions to "local".

## 7i. Phase 10 controls as built (details: ADR-0011)

- **Reverse proxy:** Nginx Proxy Manager terminates TLS. The studio publishes no host port by default.
  NPM reaches it over the shared network `npm_proxy` as `book-studio-app:8765`. Core trusts
  `X-Forwarded-*` only from that network's subnet; `validate.sh` fails if the subnet changes.
- **Other containers on `npm_proxy`** can reach Core's HTTP port, as NPM does. Every request still
  needs the Host, Origin, session and CSRF checks of §7h. Do not put untrusted services on that network.
- **Operator controls:**
  - `PBS_ALLOW_CLOUD=false` forces local-only at the egress gate, whatever the in-app setting;
  - `PBS_LOCAL_AI_HOSTS` is the only list of hosts treated as local (plain names or IPv4 addresses,
    set in the environment, never from the browser);
  - remote Ollama traffic is unencrypted HTTP, so use it only on a trusted LAN or over a VPN.
- **Files on the server:**
  - data folder owned by uid 10001, mode 700;
  - master key outside it, owner 10001, mode 400;
  - backups folder and `deploy/.env` root-only (600 and 700);
  - `validate.sh` checks the data folder and key modes.
- **Backups:** verified before they are kept or restored. Verification rejects absolute paths, `..`,
  links and device files and checks database integrity. Archives hold the encrypted key file but never
  the master key.
- **NPM's own admin:** keep port 81 on 127.0.0.1 (SSH tunnel). NPM logs an `INITIAL_ADMIN_PASSWORD` in
  plain text, so remove it after first start and change the password.

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
