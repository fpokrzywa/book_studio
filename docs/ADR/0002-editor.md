# ADR 0002: Manuscript editor: Markdown source editor (CodeMirror 6) with a Core-rendered preview

- **Status:** Accepted (Phase 02)
- **Date:** 2026-11-22
- **Deciders:** the user (owner); Claude Code (architect)

## Context

Prompt 02 asks for a pleasant editing experience "chosen for LOSSLESS preservation" of headings, lists, task lists, quotes, links, tables, code, images with alt text and captions, math, footnotes and citations. It also requires that chapter text, editor content and export round-trip without silently destroying any of them.

## Options considered

| Option | Fidelity | Effort / risk | Accessibility |
|---|---|---|---|
| **A. Source editor (CodeMirror 6) + live preview rendered by Core** | Lossless by construction: the editor edits the canonical BookMD text itself | Low. One parser and one renderer, shared with export | Good. CodeMirror is a contenteditable with role=textbox and a configurable label, plus a plain `<textarea>` mode |
| B. WYSIWYG (TipTap/ProseMirror) with a custom schema | Every BookMD construct needs a node type plus a two-way Markdown mapping. Each gap is a silent-loss risk (table captions, figure alt vs caption, citations, attributes, footnotes) | High. A second document model to keep in sync | Mixed: complex toolbars and menus |
| C. Plain textarea only | Lossless | Lowest | Good, but no syntax help |

## Decision

**Option A, with C as a user-selectable mode.**

- The editor holds the BookMD source exactly as stored. Nothing is transformed on load or save beyond normalizing CRLF to LF.
- The preview is rendered by Core (`POST /api/projects/{id}/preview`) with the same `document.html` renderer as the HTML export, and sanitized by nh3. It is shown through the single audited `SanitizedHtml` component. Preview and export cannot drift apart.
- Formatting notes under the preview surface fidelity warnings: missing alt text, images not in the project, web images not loaded, unsupported content, missing footnotes, duplicate anchors.
- CodeMirror does **not** capture Tab, so keyboard users can always leave the editor. "Plain text editor" switches to a native textarea; the preference is stored per browser.
- "Insert image" uploads an image as a project asset and inserts `![Caption](asset:<hash>){alt="…"}`. Alt text is required in the dialog.

## Consequences

- (+) Round-trip fidelity is guaranteed for the editor itself. The parser/serializer round trip is proven by fixtures and 150 property-based examples (`tests/test_document_engine.py`).
- (+) One parser and one renderer, all in Core.
- (−) Writers see Markdown syntax. Mitigations: syntax colouring, live preview, the image dialog, and help text. A WYSIWYG mode can be added later **only** if it passes the same fidelity suite (re-open this ADR).
- (−) Unit tests run CodeMirror only in the browser (Playwright). jsdom tests use a textarea stand-in with the same contract (`src/test/fakeSourceEditor.tsx`).
