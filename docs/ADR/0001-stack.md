# ADR 0001: Technology stack, dependency assessment and fallbacks

- **Status:** Proposed (accepted when the user approves Phase 00; items marked ⚠ need validation in the named phase)
- **Date:** 2026-11-22
- **Deciders:** the user (owner); Claude Code (architect)

## 1. Context

PBS is a personal, local-first, AI-assisted book studio (see PRD.md). It must keep complex documents faithful from import to export, stay usable offline, and later ship as a macOS/Windows desktop app. The user's prompt pack gives a default stack. This ADR confirms it against the **observed environment** and records where we deviate or need fallbacks.

### 1.1 Observed environment (inspected 2026-11-22, dev machine)

| Item | Observed | Implication |
|---|---|---|
| OS | Windows 11 Pro for Workstations (build 26300), x64, Xeon Platinum 8160, 512 GB RAM, 3.6 TB free on S: | Windows-first development. macOS untested until a Mac/CI runner is available |
| Repo | `S:\Development_2026\book_studio`: **not yet a git repo**. Contains only `personal_book_studio_claude_code_prompts.md`. Remote `github.com/fpokrzywa/book_studio` exists, is **empty and PUBLIC** | Public-repo hygiene is mandatory (SECURITY §7) |
| Git / gh | git 2.50.1, gh 2.96.0 | OK |
| Python | Default `python`/`py` → **CPython 3.15.2**; also 3.13.1 (python.org) and 3.12.13 (uv-managed); `python3` alias is the Microsoft Store stub | Do **not** use 3.15 (wheel lag risk). Pin 3.12 via uv |
| uv / pip | uv 0.11.15, pip 26.2.2 | uv manages venv + lockfile |
| SQLite (in Python) | 3.12 (uv): SQLite 3.50.4, FTS5 ✔; 3.13: SQLite 3.45.3, FTS5 ✔ | FTS5 available. `RETURNING` needs ≥3.35 ✔ |
| Node / pnpm / npm | Node 26.13.0, pnpm 10.33.0, npm 11.6.2 | Node 26 is the LTS line as of Oct 2026. Pin `engines.node >=22` and use pnpm |
| Rust | rustc/cargo 1.95.0, host `x86_64-pc-windows-msvc`; VS Build Tools present (VS 18 and 2019 BuildTools folders); WebView2 runtime 157.0.4341.60 | Tauri 2 prerequisites likely satisfied ⚠ (verify the C++ workload in Phase 10). Note: Git's `/usr/bin/link.exe` shadows MSVC `link.exe` in Git Bash. Build Tauri from PowerShell / Developer prompt |
| Docker | 29.9.2 | Optional for CI parity. Not a runtime dependency |
| Playwright browsers | Chromium builds cached in `%LOCALAPPDATA%\ms-playwright` | E2E can run locally |
| **Not installed** | Pandoc, Java (→ no EPUBCheck), Ollama, Tesseract, Calibre (`ebook-convert`), GTK/Pango (no MSYS2), Typst CLI, sqlite3 CLI | Each becomes a detected, optional capability with a labeled fallback (§5) |

## 2. Decision

### 2.1 Frontend (`apps/studio-ui`)
- **React 19 + TypeScript (strict) + Vite**, package manager **pnpm**.
- **React Router** (declarative mode) for routing. **TanStack Query** for server state.
- **React Aria Components** for accessible primitives. Original component styling via CSS Modules + design tokens. No third-party visual theme.
- Editor: Phase 01 uses an accessible `<textarea>` plus server-rendered preview. Phase 02 runs a fidelity bake-off and records **ADR-0002**: CodeMirror 6 (source mode, lossless by construction) is the leading candidate. A TipTap/ProseMirror WYSIWYG is admitted only if it passes the full BDM fidelity suite.
- **Vitest + React Testing Library** (+ `@testing-library/user-event`, `vitest-axe`). **Playwright** for E2E.
- **ESLint** (flat config, `typescript-eslint`, `jsx-a11y`) + **Prettier**.
- API types generated from OpenAPI with `openapi-typescript` + `openapi-fetch`.

### 2.2 Backend (`apps/studio-core`)
- **CPython 3.12** (`.python-version`), managed by **uv** (`uv.lock` committed).
- **FastAPI** + **uvicorn** (bound to 127.0.0.1), **Pydantic v2**, **pydantic-settings**.
- **SQLAlchemy 2.x** (sync engine in a threadpool; jobs use their own connections) + **Alembic** (batch mode).
- **SQLite** (WAL) + **FTS5**. Optional **sqlite-vec** for embeddings ⚠ (Phase 04), with a numpy fallback.
- **markdown-it-py** + **mdit-py-plugins** (BookMD parser), **nh3** (HTML sanitization), **defusedxml**.
- **structlog** (JSON logs + redaction), **platformdirs**, **keyring** (Phase 03), **httpx** (provider calls, Phase 03).
- **pytest**, **pytest-asyncio**, **hypothesis** (round-trip property tests), **ruff** (lint + format), **mypy --strict** on `domain/`, `document/`, `security/`, **import-linter** (layering and the no-network-outside-providers contract).

### 2.3 Publishing toolchain (Phases 02 spike → 07)
- **HTML / Markdown / EPUB 3: native writers** in Core, built from BDM. EPUB is assembled with `zipfile` (no EbookLib, which is AGPL).
- **Print PDF: WeasyPrint** (CSS Paged Media) ⚠. Windows needs the Pango runtime. Spike in Phase 02 (see §5 fallbacks).
- **DOCX: Pandoc** (external, user-installed, invoked with `--sandbox`) from a generated Pandoc JSON AST plus a PBS `reference.docx`. Fallback: **python-docx** writer with explicit loss warnings.
- **Imports:** Markdown/TXT native; HTML → nh3-cleaned → BDM; DOCX via Pandoc (preferred) or **mammoth** (fallback); PDF via **pypdf** (+ **pdfplumber** for layout-aware extraction ⚠). No PyMuPDF (AGPL).
- **Math:** `latex2mathml` (TeX → MathML for HTML/EPUB); `ziamath` (MathML → SVG for PDF) ⚠.
- **Validation:** `pypdf` (page boxes, count, fonts), native EPUB structure checks, optional **EPUBCheck** (needs Java 11+), DOCX OOXML checks via zip + XML schema sanity.
- **Fonts:** bundled SIL OFL fonts only.

### 2.4 Desktop (Phase 10)
- **Tauri 2** shell. Core packaged as a sidecar with **PyInstaller** (onedir) per OS/arch, with Nuitka as an alternative ⚠.

### 2.5 Things we explicitly do **not** use
Postgres, Redis, Celery/RQ, Electron, cloud sync, analytics SDKs, CDN-hosted assets, AGPL libraries (PyMuPDF, EbookLib), `bleach` (deprecated), `python-jose`/JWT (not needed; opaque session token).

## 3. Rationale (key trade-offs)

| Decision | Alternatives considered | Why |
|---|---|---|
| Markdown source + BDM as canonical | WYSIWYG-first (ProseMirror JSON canonical); Pandoc AST canonical | Text source can't silently drop structure. BDM adds stable IDs and per-block provenance that Pandoc AST lacks. A Pandoc AST writer still exists for DOCX |
| Single Core-side parser (Python) | Parse in the browser (remark/unified) as well | One parser means no JS/Python divergence. Preview = export renderer |
| Single `studio.db` | DB per project | Atomic job + revision commits, simple FTS and migrations. Isolation via composite FKs + tests. Backups are logical (manifest/1), so portable across schema versions |
| Native EPUB writer | Pandoc EPUB; EbookLib | Full control of accessibility metadata and nav, deterministic zips, no AGPL, no Pandoc requirement |
| WeasyPrint for PDF | Typst; headless Chromium; Prince (commercial); LaTeX | CSS shared with HTML preview, mature paged-media support, BSD license. Fallbacks retained |
| Python 3.12 | 3.13, 3.15 | Broadest wheel availability (pydantic-core, nh3, lxml, WeasyPrint deps) and PyInstaller maturity |
| React Aria Components | Radix, MUI, Chakra, shadcn | Strongest a11y behavior (incl. keyboard DnD), unstyled → original look |

## 4. Dependency reliability assessment

Legend: ✅ low risk · ⚠ verify · ⛔ avoid

| Package / tool | License | Risk | Notes and checks |
|---|---|---|---|
| FastAPI, uvicorn, Pydantic v2, SQLAlchemy 2, Alembic | MIT / BSD | ✅ | Pin minor versions. Watch FastAPI ⇄ Pydantic compatibility |
| markdown-it-py + mdit-py-plugins | MIT | ✅/⚠ | Plugin APIs change occasionally; pin them. The citation rule is ours |
| nh3 | MIT | ✅ | Rust wheel; check for CPython 3.12 win/mac wheels (expected) |
| keyring | MIT | ⚠ | Backends differ by OS. In headless CI, use the `keyring.backends.null`/test backend. Verify the macOS sidecar has keychain entitlement in Phase 10 |
| structlog, platformdirs, httpx, defusedxml | MIT/BSD/PSF | ✅ | |
| WeasyPrint | BSD-3 | ⚠ **OS blocker** | Windows: requires Pango ≥1.44 via MSYS2 (`pacman -S mingw-w64-x86_64-pango`) and `WEASYPRINT_DLL_DIRECTORIES`; or use WeasyPrint's standalone Windows executable as a subprocess ⚠. macOS: Homebrew `pango`; bundling dylibs for notarized apps is laborious |
| Pandoc | GPL-2.0+ | ⚠ licensing/install | User installs (winget `JohnMacFarlane.Pandoc`, brew `pandoc`). Invoked as a separate process. Don't bundle in distributed binaries without GPL compliance. Version floor ≥3.1 (for `--sandbox` and figure handling) ⚠ |
| EPUBCheck | BSD-3 | ⚠ needs Java 11+ | Optional. "Unavailable" state if Java/JAR missing |
| python-docx | MIT | ✅ | No native footnote API → fallback DOCX loses footnotes (become endnotes-as-text) → labeled lossy |
| mammoth | BSD-2 | ✅ | DOCX → HTML; drops some styling by design. Report lists losses |
| pypdf | BSD-3 | ✅ | Text extraction quality varies. Scanned detection via low text/page heuristic |
| pdfplumber (pdfminer.six) | MIT | ⚠ | Slower; use for layout-aware extraction on demand |
| latex2mathml | MIT | ⚠ | Coverage of LaTeX macros is partial → per-equation warnings |
| ziamath | MIT | ⚠ | Small project; verify maintenance + output quality in the Phase 02 spike. Fallback: render via Typst, or show LaTeX source |
| typst (PyPI wheel) | Apache-2.0 | ⚠ | Fallback PDF engine with no system deps. Needs a BDM → Typst writer (extra work) |
| sqlite-vec | MIT/Apache | ⚠ | Requires `enable_load_extension`. Not available in every Python build (python.org Windows yes, some macOS builds no). Numpy fallback |
| Official AI SDKs: `openai` (Apache-2.0), `anthropic` (MIT), `google-genai` (Apache-2.0), `groq` (Apache-2.0) | — | ⚠ churn | Verify current SDKs, endpoints and model discovery APIs in Phase 03 against official docs. Adapters isolate churn. Optionally use raw `httpx` where an SDK is heavy |
| Ollama | MIT | ⚠ not installed | Local HTTP API. Health check + model list. Install guidance only |
| React 19, Vite, React Router, TanStack Query, React Aria Components, CodeMirror 6 | MIT / Apache-2.0 | ✅ | Pin majors |
| Playwright | Apache-2.0 | ✅ | Use bundled Chromium for E2E |
| Tauri 2 | MIT/Apache-2.0 | ⚠ | Sidecar + permissions model. WebView2 on Windows present. macOS signing/notarization needs an Apple Developer account |
| PyInstaller | GPL-2.0 w/ bootloader exception | ⚠ | Bundling allowed. AV false positives on Windows. Must collect native libs (Pango) manually |
| Calibre `ebook-convert` | GPL-3.0 | ⚠ optional | MOBI/AZW3 only, user-installed, labeled external |
| PyMuPDF / EbookLib | AGPL-3.0 | ⛔ | Excluded by license gate |
| bleach | Apache-2.0 | ⛔ | Deprecated; use nh3 |

## 5. OS-specific blockers and explicit fallbacks

| Capability | Windows blocker | macOS blocker | Primary | Fallback 1 | Fallback 2 | User-visible state when missing |
|---|---|---|---|---|---|---|
| Print PDF | Pango/GTK runtime not present | Homebrew pango; dylib bundling/notarization | WeasyPrint (Python lib) | WeasyPrint standalone exe / Typst wheel | Headless Chromium print (Playwright) | "PDF export unavailable: install … (guide)" |
| DOCX export (full) | Pandoc not installed | same | Pandoc | python-docx (lossy, labeled) | — | "DOCX limited mode: footnotes/math simplified" |
| DOCX import | Pandoc not installed | same | Pandoc → JSON AST | mammoth → HTML → BDM | — | Import report lists losses |
| EPUB validation | No Java | No Java | EPUBCheck | Native structural checks only | — | "EPUBCheck: unavailable", never "passed" |
| Local AI | Ollama not installed | same | Ollama | Mock adapter (dev/test only) | Cloud (only if user enables) | "No local model available" |
| Secrets | Credential Manager (OK) | Keychain prompts / entitlement for sidecar | keyring | Session env vars (warned) | — | Banner: insecure key source |
| Embeddings | sqlite-vec load ext. | Python build may lack ext. loading | sqlite-vec | numpy brute force | FTS-only | "Semantic search off" |
| OCR | Tesseract missing | same | — (later feature) | — | — | "Scanned PDF: text not extractable" |
| MOBI/AZW3 | Calibre missing | same | Calibre CLI | — | — | Option hidden behind "external converter not found" |
| Desktop build | MSVC C++ workload ⚠, signing cert absent → SmartScreen warning | Apple Developer ID + notarization; Intel+ARM builds | Tauri 2 + PyInstaller sidecar | Browser-mode app (always available) | — | Documented unsigned-build limitations |

## 6. Python sidecar bundling constraints (Phase 10 preview)

> Superseded by ADR-0010 (2026-11-23): the studio is now a self-hosted web application and no desktop
> sidecar is planned. This section is kept for the record.

1. A separate PyInstaller build per target triple (`x86_64-pc-windows-msvc`, `aarch64-apple-darwin`, `x86_64-apple-darwin`). Tauri's `externalBin` requires the `-<target-triple>` suffix.
2. Native libs (Pango/cairo/harfbuzz/fontconfig for WeasyPrint) must be collected and, on macOS, each dylib codesigned with hardened runtime before notarization.
3. Startup time of a onedir bundle (~1–3 s) needs a splash/"starting" state in the shell.
4. The sidecar receives `PBS_WORKSPACE`, `PBS_PORT=0` (it picks a free port and reports it on stdout) and the session token via stdin. Not argv, which `ps` would show.
5. Single-instance lock: a Tauri plugin + a workspace lock file in Core (`runtime/core.lock`) so two Cores never share one DB.
6. Antivirus false positives for PyInstaller on Windows: code signing reduces them, and Nuitka is an alternative.

## 7. Consequences

- (+) Fidelity is protected by construction. Preview, EPUB and PDF share one renderer. Runs fully offline.
- (+) Few heavyweight dependencies. Every optional tool degrades visibly.
- (−) More native writer code (EPUB, HTML, Markdown, Pandoc-AST) to own and test.
- (−) PDF engine installation on Windows is the biggest practical hurdle. It is de-risked by a Phase 02 spike.
- (−) Markdown-source editing may feel less friendly than WYSIWYG. ADR-0002 revisits this after the fidelity suite exists.

## 7a. Addendum: versions as installed in Phase 01 (2026-11-22)

Validation item 1 is resolved: every Phase 01 dependency installed from wheels on CPython 3.12.13 (win-x64). Pinned by lockfiles (`apps/studio-core/uv.lock`, `pnpm-lock.yaml`). Notable versions and constraints:

| Area | Installed | Note |
|---|---|---|
| Backend | FastAPI 0.165, Starlette 1.10, Pydantic 2.14, SQLAlchemy 2.1.9, Alembic 1.20, structlog 26.1, markdown-it-py 4.3, uvicorn 0.54 | Starlette's TestClient warns that httpx support is deprecated (filtered in tests; revisit when it is removed) |
| Frontend | React 19.3, React Router 8.5 (data router; `useBlocker` for unsaved-changes guard), TanStack Query 5, React Aria Components 1.22, Vite 8.3, Vitest 5.1 | |
| TypeScript | **6.0.3, not 7.x** | typescript-eslint 8.73 supports `typescript <6.1`. TS 7 (native compiler) waits until the lint toolchain supports it |
| ESLint | **9.39, not 10.x** | eslint-plugin-jsx-a11y 6.10 peers on ESLint ≤9 |
| E2E | Playwright 1.65 (Chromium 159), @axe-core/playwright | |
| Fonts | Literata (variable), Atkinson Hyperlegible: SIL OFL, bundled via Fontsource | |

Environment finding: `uv` must use `UV_LINK_MODE=copy` on this machine. Hard links from the C: cache to the S: repo fail with OS error 396. All scripts set it.

## 8. Validation required (tracked in BUILD_STATE)

1. ✔ (win-x64, Phase 01) / ⚠ mac-arm64 still unverified: Python 3.12 wheels for every dependency.
2. ⚠ WeasyPrint on this Windows machine (MSYS2 Pango vs standalone exe) (Phase 02 spike).
3. ⚠ ziamath / latex2mathml quality on the math fixtures (Phase 02 spike).
4. ⚠ Pandoc version and `--sandbox` behavior with images in DOCX (Phase 02 spike).
5. ⚠ Current official AI SDK APIs and model discovery (Phase 03).
6. ⚠ KDP specifications and AI-disclosure wording, fetched from the official pages, with checked-on dates (Phase 07).
