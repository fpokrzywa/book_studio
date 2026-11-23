# Personal Book Studio

A private, self-hosted studio for writing books, from idea to a validated publishing package. It is a web application: you run it on your own Ubuntu server with Docker Compose (or on your own computer while developing) and open it in any modern browser over HTTPS. One author, one signed-in account, no cloud sync. Everything you write stays on your own server.

**Run it on a server:** [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) (Ubuntu, Docker Compose, Nginx Proxy Manager), then [docs/OPERATIONS.md](docs/OPERATIONS.md) for backups, updates and monitoring. In short:

```sh
sudo git clone https://github.com/fpokrzywa/book_studio.git /opt/book-studio && cd /opt/book-studio
sudo deploy/scripts/install.sh --domain books.example.com      # then add the NPM proxy host
sudo deploy/scripts/backup.sh                                     # verified whole-studio backup
sudo deploy/scripts/update.sh --pull                              # backup, build, migrate, validate
```

**Release status:** [docs/FINAL_ACCEPTANCE_REPORT.md](docs/FINAL_ACCEPTANCE_REPORT.md) (READY FOR PERSONAL USE, with conditions), with [FEATURE_MATRIX](docs/FEATURE_MATRIX.md), [DEPLOYMENT_VERIFICATION](docs/DEPLOYMENT_VERIFICATION.md), [KNOWN_ISSUES](docs/KNOWN_ISSUES.md) and the author's [USER_GUIDE](docs/USER_GUIDE.md).

**Develop it:** the sections below.

**Status: Phase 11 (final acceptance testing and stabilisation).** These work today:

- **Library, manuscript tree and editor:** books, parts, chapters and sections; a Markdown editor with live preview (tables, math, citations, footnotes, images with alt text and captions).
- **Saving and history:** autosaved drafts, immutable revisions you can compare, label and restore.
- **Import and export:** Markdown, text, HTML, Word and text-based PDF in; Markdown, HTML, EPUB, Word and print PDF out, plus covers and a publish package.
- **AI (optional):** local or cloud models behind an egress gate, durable jobs, suggestions you accept or reject; knowledge sources, evidence and citations; planning and section-by-section writing.
- **Series, translations, narration and interviews** (Phase 08).
- **Web deployment:** sign-in, encrypted key storage, a background worker (Phase 09); Ubuntu deployment behind Nginx Proxy Manager with install, update, backup, restore and rollback scripts, validated end to end (Phase 10).

See [docs/ROADMAP.md](docs/ROADMAP.md) and [docs/BUILD_STATE.md](docs/BUILD_STATE.md) for exactly what is built and tested.

### Using the studio

| Task | Where |
|---|---|
| Write | Open a chapter. Type Markdown on the left and see the preview on the right (switch with Write / Write and preview / Preview). Changes autosave as a draft; **Save** (Ctrl+S / Cmd+S) keeps a revision |
| Images | **Insert image** in the editor. The image is copied into the book and you give a caption and alt text |
| Versions | **History** in the editor: compare any two revisions side by side, add labels or notes, and restore an old version as a new revision (nothing is overwritten) |
| Arrange chapters | On the book page, drag a chapter or use **Up**, **Down**, **Indent** and **Outdent**. **Details** edits the title, slug, status and target length |
| Import | **Import** in the menu (or **Import chapters** on a book). You see the detected chapters, warnings and possible duplicates before anything is added. The uploaded file is kept unchanged |
| Back up / restore | **Create backup** on a book page. **Restore a backup** on the Library page always creates a new book |

## What's in the box

| Part | Path | Tech |
|---|---|---|
| Studio Core (local API, storage) | `apps/studio-core` | Python 3.12, FastAPI, SQLAlchemy, Alembic, SQLite |
| Studio UI | `apps/studio-ui` | React 19, TypeScript, Vite, React Router, TanStack Query, React Aria |
| End-to-end tests | `e2e` | Playwright |
| Design docs | `docs` | PRD, architecture, data model, security, ADRs, test plan, roadmap |

Every `/api` request needs a signed-in session (an HttpOnly cookie) and every change needs the session's anti-forgery header; requests from a foreign Origin or with an unexpected Host header are refused. In development Core listens on **127.0.0.1 only**; on a server only the HTTPS proxy is published (docs/DEPLOYMENT.md). In local-only mode (the default) nothing is sent to the internet.

| Part (Phase 09) | Path |
|---|---|
| Server deployment (Phase 10): Dockerfile, Compose file for Nginx Proxy Manager, install, update, backup, restore, rollback and validation scripts | `deploy/` |

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| uv | 0.5+ | https://docs.astral.sh/uv/getting-started/installation/ (uv installs Python 3.12 for you) |
| Node.js | 22 or newer | https://nodejs.org/ |
| pnpm | 10 | `corepack enable` or https://pnpm.io/installation |
| Git | any recent | |

Optional tools (Pandoc, Java/EPUBCheck, Ollama, WeasyPrint, Calibre) are **not needed for Phase 01**. The Help page lists which ones are detected.

## Setup (once)

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

**macOS (zsh/bash):**

```sh
sh scripts/setup.sh
```

The script installs Python 3.12 through uv, creates `apps/studio-core/.venv`, installs the UI packages, and installs Playwright's Chromium.

## Starting the app

**Windows:**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

**macOS:**

```sh
sh scripts/dev.sh
```

Then open **http://127.0.0.1:5173**. Press `Ctrl+C` in the terminal to stop both processes.

**First run:** the studio asks you to create its account. It needs the one-time setup code that Core writes to `.pbs-data/runtime/setup-code.txt` (the start script prints the path). You can also create the account in a terminal: `apps\studio-core\.venv\Scripts\python.exe -m pbs_core create-user author`. Forgot the password: `... -m pbs_core reset-password author`.

By default your data goes to `.pbs-data/` in the repository folder. That folder is git-ignored, so it is never committed. To use another folder, pass `-Workspace D:\Books` (Windows) or set `PBS_WORKSPACE=/path` (macOS).

What the script does, if you prefer to run the two processes yourself:

```powershell
# Terminal 1 - Core
$env:PBS_WORKSPACE = "$PWD\.pbs-data"
apps\studio-core\.venv\Scripts\python.exe -m pbs_core
```

```powershell
# Terminal 2 - UI (proxies /api to Core; your sign-in cookie passes through)
$env:PBS_WORKSPACE = "$PWD\.pbs-data"
pnpm --filter studio-ui dev
```

On macOS use `export PBS_WORKSPACE="$PWD/.pbs-data"` and `apps/studio-core/.venv/bin/python -m pbs_core`.

### Optional demo data

Demo books are created only when you ask for them, and they are labeled "Demo":

```powershell
$env:PBS_WORKSPACE = "$PWD\.pbs-data"; apps\studio-core\.venv\Scripts\python.exe -m pbs_core.tools.seed_demo
```

## Running the checks

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1
```

```sh
sh scripts/test.sh
```

This runs ruff, mypy (strict), import-layer contracts, pytest, the license gate, ESLint and Prettier, the TypeScript check, Vitest, the production build and Playwright. Add `-SkipE2E` (or `--skip-e2e`) to skip the browser tests.

Individual suites:

| What | Command |
|---|---|
| Backend tests | `cd apps/studio-core; uv run pytest` |
| Frontend unit tests | `pnpm --filter studio-ui test` |
| End-to-end | `pnpm e2e` (starts its own Core on port 18765 and UI on 15173, using a temporary workspace) |
| Regenerate the API types after changing Core contracts | `powershell -File scripts\gen-api.ps1` / `sh scripts/gen-api.sh` |

## Configuration

Core reads environment variables prefixed with `PBS_`:

| Variable | Default | Meaning |
|---|---|---|
| `PBS_WORKSPACE` | `./.pbs-data` (dev), `/data` (server) | Where the database, files, logs and runtime files live |
| `PBS_DEPLOYMENT` | `local` | `local` (loopback only) or `server` (behind the HTTPS proxy; docs/DEPLOYMENT.md) |
| `PBS_ROLE` | `all` | `all` (web and background worker in one process), `web` or `worker` |
| `PBS_PUBLIC_ORIGIN` | unset | Server only: the https address browsers use, e.g. `https://books.home.lan` |
| `PBS_TRUSTED_PROXIES` | `[]` | Server only: the proxy address whose `X-Forwarded-*` headers are trusted |
| `PBS_UI_DIST` | unset | Folder of the built UI that Core serves itself (the server image sets it) |
| `PBS_SECRET_KEY_FILE` | unset | Server: 32-byte master key (a Docker secret) for the encrypted key store |
| `PBS_LOCAL_AI_HOSTS` | `[]` | Private model hosts treated as local, e.g. `["ollama"]` |
| `PBS_SESSION_IDLE_MINUTES` / `PBS_SESSION_MAX_DAYS` | `720` / `14` | Sign-in session limits |
| `PBS_ENV` | `dev` | `dev`, `test` or `prod`. In `prod` without `PBS_WORKSPACE`, the default is `Documents/Personal Book Studio` |
| `PBS_PORT` | `8765` | Core port |
| `PBS_HOST` | `127.0.0.1` | In `local` deployment only loopback values are accepted; anything else refuses to start |
| `PBS_UI_ORIGINS` | `["http://127.0.0.1:5173","http://localhost:5173"]` | JSON list of allowed UI origins |
| `PBS_LOG_LEVEL` | `INFO` | Log level. Logs are JSON in `<workspace>/logs/`, with secrets redacted |
| `PBS_SECRET_BACKEND` | `auto` | Where AI API keys are kept: `auto` (encrypted file if `PBS_SECRET_KEY_FILE` is set, else the system credential store; a server never uses a keyring), `encrypted-file`, `keyring`, or `dev-file` (development only: a user-only file in `<workspace>/runtime/`, with a warning in the app) |
| `PBS_<PROVIDER>_API_KEY` | unset | Read-only key source, e.g. `PBS_OPENAI_API_KEY`. It is used when no key is stored, and the app warns about it |
| `PBS_AI_WORKERS` | `2` | How many AI jobs run at once (a local Ollama server always runs one at a time) |

The UI dev server reads `PBS_CORE_URL` (default `http://127.0.0.1:8765`) and `PBS_UI_PORT` (default `5173`).

## Using AI (Phase 03)

AI is optional. Nothing leaves this computer unless you allow it.

1. **Local models (recommended).** Install [Ollama](https://ollama.com), run `ollama pull <model>`, then in **AI settings** add *Ollama (local)*, click **Test connection** and then **Find models**. Only addresses on this computer are accepted.
2. **Write with AI.** In a chapter, open **AI assist**, pick a task and a model, describe what you want, and click **Ask**. The answer appears as a suggestion. Edit it if you like, then **Accept as a new revision** (undo it from History) or **Reject**. Save your changes before asking, so the model sees what you see.
3. **Cloud models.** OpenAI, Anthropic, Google Gemini, Groq and xAI (Grok) are available. Switch AI settings to *Cloud allowed* (you are asked to confirm), store the API key, and allow each book to use that provider the first time. Enter the model's price (from the provider's pricing page) to see cost estimates; without one, cost shows as unknown.
4. **AI jobs** shows every request with its stages, log, Retry/Cancel, and a usage and cost table.

Optional live check against a real provider (sends one short fixed prompt):

```powershell
$env:PBS_OPENAI_API_KEY = "<your key>"; apps\studio-core\.venv\Scripts\python.exe -m pbs_core.live_check --kind openai --model <model-id>
```

## Planning a book (Phase 05)

- **New book** asks, in four optional steps, about the reader, the promise, the shape, sources, how AI drafts reach you, and a budget cap.
- A book's **Plan** has four tabs:
  - **Brief**: reader, promise, exclusions, arc, and assumptions stated openly.
  - **Research**: your findings; measured evidence (with a source) is kept apart from notes and ideas. Search Open Library if you turn it on in AI settings. AI brainstorms for topics, search queries or KDP keywords are ideas only, and any sales, ranking, demand or search-volume claim is removed.
  - **Outline**: ask AI for a proposal, or write your own. Reorder, nest, merge, split and lock entries, approve, then **Apply to manuscript** to create the chapters. Applying a changed outline never touches chapters with text.
  - **Draft chapters**: one chapter or the whole book from the approved outline. You see an estimate first, and runs respect your budget cap and chapter limit. Every chapter arrives as a suggestion for you to review.

## Writing and reviewing (Phase 06)

- **Drafting by section.** Plan → Draft chapters now drafts each chapter one outline section at a time.
  - Each section prompt gets the brief, the local outline, summaries of earlier chapters, continuity notes, the style guide and source passages, trimmed to a token budget you set.
  - Tick "Stop after each section" to review and edit every section before the next one.
- **Write and review** (on the book page) has four tabs:
  - **Drafts**: progress per section, what each prompt included, pause, resume, cancel, retry of a failed section, and the job history. A finished chapter arrives as one suggestion in the chapter.
  - **Story bible and summaries**: continuity notes proposed by drafts (confirm or reject them) and chapter summaries (edit them).
  - **Quality checks**: local checks for repeated phrases and paragraphs, uncited factual sentences, missing citations, outline differences, broken links, missing alt text, inconsistent terms, undefined acronyms and (fiction) continuity. You can also ask for an AI review. Mark each finding (needs a source, will fix, dismissed, fixed). These are hints, not proof.
  - **Originality**: a local comparison with this book, your other books and this book's sources. No match does not prove originality.
- **Editor actions.** In AI assist, select a passage and choose rewrite, expand, shorten, change tone, clearer, remove repetition, better transitions, explain, or exercises, quiz or glossary suggestions. You see the change word by word, and code and math are kept exactly.
- **Lock against AI changes** in the chapter editor keeps AI drafts and suggestions out of a chapter.

## Publishing (Phase 07)

- **Publishing** (menu) or **Publish** (on a book) has five tabs:
  - **Book setup**: interior template, trim size, ink and paper (with KDP's page range), front and back matter, your copyright details (PBS writes no legal text and invents no ISBN), and index terms.
  - **Store details**: description, seven keywords, category ideas (unverified), reading age, and the AI disclosure checklist with KDP's definitions.
  - **Cover**: size from the final page count of the print PDF; artwork you have the rights to; typography for title, subtitle, author, spine and back text; then build the print cover, a proof with guides and the eBook cover.
  - **Build and preview**: EPUB, print PDF, Word, HTML and Markdown, each with its check report and fidelity result. The reading preview tells you whether it matches the last export; print preview pages are pictures of the same layout.
  - **Publish package**: everything in one folder and ZIP, plus the preflight report and step-by-step upload instructions. Nothing is uploaded or published for you, and passing the checks does not mean KDP will accept the book.
- **Optional EPUBCheck.** EPUB validation needs EPUBCheck (Java). Install it, or set `PBS_EPUBCHECK_JAR`; without it the report says "unavailable", never "passed".
- **KDP rules** are rule set `kdp-paperback-2026-11-22`, checked against KDP's help pages on 2026-11-22. The sources are in `docs/ADR/0008-publishing.md`.

## Series, translations, narration and interviews (Phase 08)

- **Series** (menu): group books that share a world. The story bible holds characters, places, plot threads, events and terms, with facts and relationships. Anything added by AI or imported from a book's story notes stays a *suggestion* until you approve it. **Continuity review** compares each chapter with approved canon and links every question to its passage; you decide each one (fix the text, update canon, or leave it as intended), and your decision is kept when you run the check again. The relationship map is a picture of the list beside it.
- **Pen names**: on **Author voice**, give a profile a pen name and do/avoid rules. The book page shows which voice the book uses and lets you change it.
- **Translations** (on a book): make an edition in another language. It is a separate book linked chapter by chapter. Only approved chapters are translated; the original is never changed; code, math, citations and links are protected. The result is a suggestion you accept or reject, with idioms and terms flagged to check.
- **Narration** (on a book, optional): prepare a speech-ready script of each chapter; make audio only after you turn narration on and choose an engine; export WAV files with chapter timing, a cue sheet and notes on cost, licensing and AI-voice disclosure. The export is **not** checked against ACX, Audible or KDP audiobook requirements.
- **Recorded interviews** (on a book): import audio you own, transcribe it with the engine you choose, correct speaker names, and keep chosen passages, with timestamps, as sources.

### Optional tools (none is required)

| Tool | Used for | How PBS finds it |
|---|---|---|
| [eSpeak NG](https://github.com/espeak-ng/espeak-ng) (GPL-3.0) | narration on this computer | `espeak-ng` on PATH |
| [Piper](https://github.com/rhasspy/piper) (MIT; each voice has its own licence) | narration on this computer | `piper` on PATH and `PBS_PIPER_MODEL` set to a voice model file |
| [openai-whisper](https://github.com/openai/whisper) (MIT) and [FFmpeg](https://ffmpeg.org) | transcription on this computer | `whisper` (and `ffmpeg`) on PATH |
| OpenAI speech and transcription (cloud) | narration and transcription | an OpenAI provider in AI settings, cloud mode on, and the book allowed to use it |
| EPUBCheck (Java) | EPUB validation (Phase 07) | `PBS_EPUBCHECK_JAR` or `epubcheck` on PATH |

Without these tools, the features still open: the narration script is prepared and readable, and each page says which engine is missing and how to install it. In local-only mode cloud engines are refused before anything is sent. **Narration → Speech engine** and the recordings page show what this computer has.

## Sources, evidence, voice and interviews (Phase 04)

- **Sources.** Open a book, then **Sources**, and add Markdown, text, HTML, Word or text-based PDF files. Each is kept unchanged and split into passages you can search; matched words are highlighted and every hit says why it matched. Turn **Use for AI** off to keep a source out of new AI suggestions, or **Remove** it. **Knowledge** in the menu holds shared libraries that books can opt in to.
- **Citations.** When AI assist uses your sources, each paragraph of a suggestion lists the exact passages behind it, or says **Unverified**. Accepted text cites them as `[@key, p. 3]`, and the passages are recorded in the book's **Evidence ledger**. Titles, authors, years, URLs and DOIs are never guessed; add them on a source's page.
- **Author voice.** Add samples of your own writing to describe your style, edit the style guide, then choose **Rewrite in a voice** when revising a passage. You always see the before and after first.
- **Interview.** Answer questions about your own experiences; your exact words are kept, with every version. AI may use them only as written.

## Where your data lives

```
<workspace>/
  studio.db            SQLite database (WAL). Every chapter save is an immutable revision
  projects/<id>/exports/<export-id>/<Book Title>.md
  db-backups/          automatic snapshot before every schema upgrade
  logs/core.jsonl      local logs (no manuscript text, secrets redacted)
  runtime/             setup code (until the account exists), encrypted key store, worker lock
                       and heartbeat (user-only permissions; never in backups or exports)
```

Also in the workspace: `originals/` (every imported file, byte-for-byte and read-only), `projects/<id>/assets/` (images, named by content hash) and `backups/` (project backups). To back up everything by hand, stop the app and copy the workspace folder. For one book, use **Create backup**.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `python3` opens the Microsoft Store | Expected on Windows. The scripts use the uv-managed venv (`apps\studio-core\.venv\Scripts\python.exe`), not `python3` |
| uv error *"failed to hardlink file … incompatible hardlinks (os error 396)"* | Set `UV_LINK_MODE=copy` (the scripts do this). It happens when uv's cache and the repo are on different drives or a cloud-synced folder |
| `Port 8765 is already in use` / `Port 5173 …` | Another copy is running. Close it, or start with `-CorePort 8766 -UiPort 5174` (Windows) / `PBS_PORT=8766 PBS_UI_PORT=5174` (macOS) |
| The app says *"Can't reach Personal Book Studio Core"* | Core is not running or crashed. Look at the terminal output, then start `scripts/dev.ps1` again. Your saved work is in the workspace |
| Every API call returns 401 | You are not signed in, or the session ended (12 hours unused, 14 days at most, or the password changed). Reload the page and sign in |
| AI jobs, builds or exports stay "queued" | No background worker is running. In development `PBS_ROLE` must be `all` (the default); on a server start the `worker` service |
| Core refuses to start: *"database … written by a newer version"* | You opened a workspace with an older checkout. Switch back to the newer version. Core never downgrades a database |
| `powershell … cannot be loaded because running scripts is disabled` | Use the `-ExecutionPolicy Bypass -File …` form shown above |
| Reset the dev data | Stop the app and delete `.pbs-data/` |

## Privacy and governance

- No telemetry, no analytics, no update checks, no web fonts from a CDN. Fonts (Literata and Atkinson Hyperlegible, SIL OFL) are bundled.
- Saved text is never overwritten: each save adds a revision, and the database refuses edits or deletions of revisions.
- Archiving is reversible and read-only. Nothing in Phase 01 deletes your writing.

This repository is public. Never commit a real manuscript, workspace or `.env` file. The `.gitignore` excludes them.
