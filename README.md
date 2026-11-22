# Personal Book Studio

A private, local-first studio for writing books, from idea to a validated publishing package. Single user, no accounts, no cloud sync. Everything you write is stored on your own disk.

**Status: Phase 02.** These work today:

- **Library:** create, search, archive and duplicate books.
- **Manuscript tree:** parts, chapters and sections, reordered with drag-and-drop or buttons.
- **Editor:** a Markdown editor with live preview. It handles tables, math, citations, footnotes and images with alt text and captions.
- **Saving:** autosaved drafts, plus immutable revisions you can compare, label and restore.
- **Import:** Markdown, text, HTML, Word (.docx) and text-based PDF.
- **Export:** Markdown (zipped with images) and HTML.
- **Backup:** one-file backup and restore.

Research, Knowledge, Publishing and AI settings are visibly marked "Not yet implemented". See [docs/ROADMAP.md](docs/ROADMAP.md) and [docs/BUILD_STATE.md](docs/BUILD_STATE.md).

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

Core listens on **127.0.0.1 only** and refuses requests without the per-launch session token, from a foreign Origin, or with an unexpected Host header. Phase 01 makes **no external network calls**.

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

By default your data goes to `.pbs-data/` in the repository folder. That folder is git-ignored, so it is never committed. To use another folder, pass `-Workspace D:\Books` (Windows) or set `PBS_WORKSPACE=/path` (macOS).

What the script does, if you prefer to run the two processes yourself:

```powershell
# Terminal 1 - Core
$env:PBS_WORKSPACE = "$PWD\.pbs-data"
apps\studio-core\.venv\Scripts\python.exe -m pbs_core
```

```powershell
# Terminal 2 - UI (reads the session token from the same workspace)
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
| `PBS_WORKSPACE` | `./.pbs-data` (dev) | Where the database, exports, logs and runtime token live |
| `PBS_ENV` | `dev` | `dev`, `test` or `prod`. In `prod` without `PBS_WORKSPACE`, the default is `Documents/Personal Book Studio` |
| `PBS_PORT` | `8765` | Core port (always bound to loopback) |
| `PBS_HOST` | `127.0.0.1` | Only loopback values are accepted; anything else refuses to start |
| `PBS_UI_ORIGINS` | `["http://127.0.0.1:5173","http://localhost:5173"]` | JSON list of allowed UI origins |
| `PBS_LOG_LEVEL` | `INFO` | Log level. Logs are JSON in `<workspace>/logs/`, with secrets redacted |
| `PBS_SECRET_BACKEND` | `auto` | Where AI API keys are kept: `auto`/`keyring` (the system credential store), or `dev-file` (development only: a user-only file in `<workspace>/runtime/`, with a warning in the app) |
| `PBS_<PROVIDER>_API_KEY` | unset | Read-only key source, e.g. `PBS_OPENAI_API_KEY`. It is used when no key is stored, and the app warns about it |
| `PBS_AI_WORKERS` | `2` | How many AI jobs run at once (a local Ollama server always runs one at a time) |

The UI dev server reads `PBS_WORKSPACE`, `PBS_CORE_URL` (default `http://127.0.0.1:8765`) and `PBS_UI_PORT` (default `5173`).

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

## Where your data lives

```
<workspace>/
  studio.db            SQLite database (WAL). Every chapter save is an immutable revision
  projects/<id>/exports/<export-id>/<Book Title>.md
  db-backups/          automatic snapshot before every schema upgrade
  logs/core.jsonl      local logs (no manuscript text, secrets redacted)
  runtime/             per-launch session token (user-only permissions)
```

Also in the workspace: `originals/` (every imported file, byte-for-byte and read-only), `projects/<id>/assets/` (images, named by content hash) and `backups/` (project backups). To back up everything by hand, stop the app and copy the workspace folder. For one book, use **Create backup**.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `python3` opens the Microsoft Store | Expected on Windows. The scripts use the uv-managed venv (`apps\studio-core\.venv\Scripts\python.exe`), not `python3` |
| uv error *"failed to hardlink file … incompatible hardlinks (os error 396)"* | Set `UV_LINK_MODE=copy` (the scripts do this). It happens when uv's cache and the repo are on different drives or a cloud-synced folder |
| `Port 8765 is already in use` / `Port 5173 …` | Another copy is running. Close it, or start with `-CorePort 8766 -UiPort 5174` (Windows) / `PBS_PORT=8766 PBS_UI_PORT=5174` (macOS) |
| The app says *"Can't reach Personal Book Studio Core"* | Core is not running or crashed. Look at the terminal output, then start `scripts/dev.ps1` again. Your saved work is in the workspace |
| Every API call returns 401 | The UI proxy reads the token from `<workspace>/runtime/session.token`. Make sure Core and the UI use the **same** `PBS_WORKSPACE` |
| Core refuses to start: *"database … written by a newer version"* | You opened a workspace with an older checkout. Switch back to the newer version. Core never downgrades a database |
| `powershell … cannot be loaded because running scripts is disabled` | Use the `-ExecutionPolicy Bypass -File …` form shown above |
| Rust/Tauri builds fail in Git Bash with a strange `link.exe` error | Git's `/usr/bin/link.exe` shadows MSVC's. Build from PowerShell (relevant from Phase 10) |
| Reset the dev data | Stop the app and delete `.pbs-data/` |

## Privacy and governance

- No telemetry, no analytics, no update checks, no web fonts from a CDN. Fonts (Literata and Atkinson Hyperlegible, SIL OFL) are bundled.
- Saved text is never overwritten: each save adds a revision, and the database refuses edits or deletions of revisions.
- Archiving is reversible and read-only. Nothing in Phase 01 deletes your writing.

This repository is public. Never commit a real manuscript, workspace or `.env` file. The `.gitignore` excludes them.
