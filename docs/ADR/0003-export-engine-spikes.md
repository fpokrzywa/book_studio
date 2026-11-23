# ADR 0003: Export-engine spikes (Phase 02) and print-PDF engine recommendation

- **Status:** Accepted in Phase 07: Typst is the print-PDF engine (see ADR-0008). WeasyPrint and Pandoc remain unused.
- **Date:** 2026-11-22

## Context

ADR-0001 chose WeasyPrint for print PDF, with Typst and headless Chromium as fallbacks, and asked for spikes in Phase 02 on the development machine (Windows 11, CPython 3.12, no GTK/Pango, no Pandoc, no Java).

## Spike results (run 2026-11-22 in isolated `uv run --isolated` environments; nothing was installed into the project)

| Spike | Command (summary) | Result |
|---|---|---|
| WeasyPrint 6.x on Windows | `import weasyprint; HTML(string='<p>x</p>').write_pdf()` | **Failed.** WeasyPrint could not load the Pango/GObject libraries and pointed to its Windows troubleshooting page. It needs MSYS2 + Pango (or its standalone executable) on Windows and Homebrew libraries on macOS, which is hard to bundle and notarize (ADR-0001 §5/§6) |
| Typst via the `typst` PyPI wheel | `typst.compile('t.typ')` with a heading, emphasis and an integral | **Passed.** 12.5 KB PDF, no system dependencies, fully offline |
| LaTeX → SVG math with `ziamath` | `ziamath.Latex(r'\int_0^1 x^2\,dx=\frac{1}{3}').svg()` | **Passed.** 8.8 KB SVG, pure Python |
| LaTeX → MathML with `latex2mathml` | Used in production since Phase 02 (preview and HTML export) | **Passed** on the fixtures. Coverage of exotic macros is partial; failures fall back to showing the source with a warning |
| Pandoc DOCX | Not run: Pandoc is not installed on this machine | **Deferred.** Needs the user to install Pandoc (D6) |

## Recommendation (for Phase 07)

1. **Make Typst the primary print-PDF engine** (Apache-2.0, a wheel per platform, deterministic). That means writing a `bdm/1 → Typst` writer. Typst has native math (convert TeX with a small mapper, or embed ziamath SVG), footnotes, figures with captions, tables, page setup (trim, mirrored margins, running headers) and fonts loaded from files (bundle OFL fonts).
2. Keep WeasyPrint as an **optional** engine when the user installs it with its libraries. The capability report already detects it.
3. Keep the HTML renderer as the single source for HTML and EPUB.
4. DOCX: Pandoc when installed; python-docx fallback labelled lossy (unchanged from ADR-0001).

## Consequences

- (+) Print PDF works on a clean Windows or macOS machine without GTK, and the desktop sidecar stays bundleable.
- (−) A second rendering path (Typst) must pass the same fidelity fixtures as HTML. Phase 07 adds the PDF inspections from TEST_PLAN (page size, page count, embedded fonts, text per page).
