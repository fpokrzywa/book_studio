# ADR-0008: Publishing engine: assembly, five formats, covers, preflight and the KDP package

Status: Accepted (Phase 07, 2026-11-22). Supersedes the "Proposed" status of ADR-0003 (D7): **Typst is the print-PDF engine.**

## Context
Phase 07 turns a finished manuscript into upload-ready files. The constraints:
- **Exports:** configurable front and back matter; four interior templates; Markdown, HTML, editable DOCX, accessible EPUB and a print-ready interior PDF from deterministic templates; honest round-trip fidelity reporting.
- **Covers:** typography layers (never model-drawn lettering), and a full-wrap print cover sized from the final page count.
- **Preflight:** checks against current KDP specifications, saved with every export.
- **Handoff:** a metadata handoff and a package for manual upload. PBS never auto-publishes, fabricates legal text or ISBNs, or promises approval.

The development machine has no Pandoc, Java/EPUBCheck, GTK (WeasyPrint) or MOBI converter (ADR-0003).

## KDP specifications used (checked 2026-11-22)
The rules live in `pbs_core/publishing/kdp_rules.py` with their source URLs. They are versioned as `RULESET = "kdp-paperback-2026-11-22"`, and the UI and every report show that version.

| Page | URL | Used for |
|---|---|---|
| Trim, bleed, margins | https://kdp.amazon.com/en_US/help/topic/GVBQ3CMEQW3W2VL6 | 16 paperback trims with page ranges per ink and paper; 0.125 in bleed; gutter by page count (0.375 / 0.5 / 0.625 / 0.75 / 0.875 in); outside margin ≥ 0.25 in (0.375 with bleed) |
| Print manuscript | https://kdp.amazon.com/en_US/help/topic/G202145060 | Embedded fonts (full embedding recommended); 300 DPI images; 650 MB; no annotations, bookmarks or encryption; blank-page limits (4 / 10); text ≥ 7 pt; even page numbers on the left |
| Print cover (overview) | https://kdp.amazon.com/en_US/help/topic/G202187850 | Cover calculator; points to the paperback cover page |
| Paperback cover | https://kdp.amazon.com/en_US/help/topic/G201953020 | Width = bleed + back + spine + front + bleed; spine per page: white 0.002252, cream 0.0025, standard color 0.002252, premium color 0.002347 in; spine text from 79 pages, 0.0625 in from each edge; text 0.125 in inside the trim; single PDF |
| Barcodes | https://kdp.amazon.com/en_US/help/topic/G5HDYGP4BXLX4RUW | Suggested barcode 2 × 1.2 in, at least 0.25 in from the spine and trim; images or text in the barcode area are rejected |
| Kindle Previewer | https://kdp.amazon.com/en_US/help/topic/G202131170 | Manual EPUB check step |
| eBook cover | https://kdp.amazon.com/en_US/help/topic/G200645690 | 1600 × 2560 px ideal, JPEG or TIFF, RGB, under 50 MB |
| Content guidelines (AI) | https://kdp.amazon.com/en_US/help/topic/G200672390 | AI-generated (disclose) vs AI-assisted (no disclosure) definitions |
| Keywords and metadata | https://kdp.amazon.com/en_US/help/topic/G201298500, https://kdp.amazon.com/en_US/help/topic/G201097560 | Up to 7 keywords; up to 3 categories; title + subtitle under 200 characters; no sales rank, "free", reviews, contact details or other authors in metadata |

**Not published by KDP, so not invented:**
- the exact position of KDP's own barcode;
- hardcover wraps (PBS builds paperback covers only);
- a per-keyword character limit.

These are reported as "check manually".

## Decisions

### 1. One assembled book for every format
`publishing/book.assemble` reads the head revision of every chapter (tree order), the publishing profile, the book's sources and assets. Every writer works from that one assembly, so these are identical in every format:
- chapter numbers;
- figure, table and listing numbers (`Figure 2.1`, per chapter, per template);
- citation labels (author–year from author-entered source fields, else a short title);
- front and back matter.

### 2. Front and back matter, without fabrication
**The 18 kinds:**
- front: half title, title page, copyright, dedication, epigraph, contents, foreword, preface, introduction;
- back: acknowledgments, appendix, notes, glossary, bibliography, index, about the author, discussion guide, call to action.

**Generated items** use only what the book has:
- title page: title, subtitle, author;
- contents;
- bibliography: cited keys plus the author's source fields;
- glossary: "term: definition" lines plus confirmed story-bible terms;
- index: author-entered terms; page numbers in the PDF via Typst queries, chapter links elsewhere.

**Text items** are the author's own Markdown. An item turned on with no text is left out with a warning.

**The copyright page** shows only the author's entries: holder, year, edition, an ISBN whose check digit is valid, and their own notice. PBS writes no "All rights reserved", no legal text and no ISBN. If nothing is entered, the page is left out and reported.

### 3. Interior templates
Four templates: technical manual, nonfiction, novel and workbook. Each sets:
- trim, fonts, sizes and leading;
- inside, outside, top and bottom margins;
- chapter openings (right-hand page or any page) and the chapter label;
- caption numbering, running heads, page-number position, TOC depth, notes style (footnotes or chapter endnotes) and justification.

**Fonts** are Typst's built-in, freely licensed set, used with system fonts ignored so builds are reproducible:
- Libertinus Serif (OFL);
- New Computer Modern and its Math face (GUST);
- DejaVu Sans Mono (Bitstream Vera).

The licenses are listed in every package.

### 4. Five writers and their documented substitutes
| Format | Engine | Substitutes (always reported) |
|---|---|---|
| Markdown | chapter source verbatim + front matter, ZIP with images | none |
| HTML | the shared renderer (one file, images embedded, CSP, no scripts) | none |
| EPUB 3 | own writer: XHTML per part, nav with landmarks, MathML, schema.org accessibility metadata, eBook cover, deterministic ZIP | none |
| DOCX | python-docx with named styles (PBS Code, PBS Equation, Caption, Heading 1–4, Quote, lists), alt text, hyperlinks, header-row tables | equations kept as LaTeX source; footnotes become chapter-end notes; the TOC is a Word field |
| Print PDF | Typst (Apache-2.0 wheel, offline) | a web link prints its address after the link text (print has no live links); equations Typst cannot take print as LaTeX source |

**PDF layout:**
- page = trim, no bleed, binding left;
- mirrored margins; chapters open on the right where the template says so;
- running heads (book title on the left, chapter title on the right), none on chapter openings or blank pages;
- page numbers on the outside;
- no bookmarks and no link annotations (KDP asks for none);
- tagged PDF with alt text and the document language.

**Gutter.** After a first layout pass, the gutter is raised to KDP's minimum for the final page count and the book is laid out again (at most 4 passes).

**Equations** go through `publishing/latex_typst.py`, a LaTeX-subset converter. Anything outside the subset becomes LaTeX source plus a report line.

**Reproducible output.** All writers are deterministic: fixed ZIP timestamps, and the PDF date taken from the book's last revision. The same book gives the same bytes.

### 5. Round-trip fidelity
`publishing/fidelity.py` inventories the source: chapter order, headings, tables and cells, hyperlinks, code blocks, equations, images and alt text, captions and citation labels. It then opens each export:
- HTML and EPUB are parsed with lxml;
- DOCX is read with python-docx;
- the PDF's text and image objects are read with pypdf;
- Markdown is checked for verbatim chapter text.

Each element is reported as ok, degraded (a documented substitute) or missing. Nothing is dropped without a report line.

### 6. Previews
- **HTML reading preview:** the same writer as the export. The UI says whether it is byte-identical to the last HTML export (SHA-256 compared).
- **Print preview:** PNG page images rendered from the same Typst layout. The UI and response headers say these are images, not the PDF file. "Open" on a build serves the actual exported file.

### 7. Covers
- **Print cover:** one PDF page sized `kdp_rules.cover_spec(trim, ink/paper, page count)`, where the page count comes from the latest interior PDF. A new PDF with a different page count marks the last cover stale, and building again resizes it.
- **Layers:**
  - artwork the author uploaded and licensed: a rights confirmation is required, and its effective DPI is checked;
  - typography layers (title, subtitle, author, spine, back text) set by Typst in embedded fonts, inside a 0.375 in safe area;
  - spine text only from 79 pages, and only if it fits at ≥ 7 pt within 0.0625 in of each spine edge;
  - a white, clear 2 × 1.2 in barcode area 0.25 in from the spine and the bottom trim.
- **Also built:** a proof copy with trim, fold, safe-area and barcode guides (not for upload), and a 1600 × 2560 px JPEG eBook cover.
- **Image generation:** no provider is configured, and the UI says so. Lettering is never drawn by an image model.
- **Colour:** CMYK conversion is not done; the report asks for a printed proof.

### 7a. Paper types without a published spine factor
KDP publishes no spine thickness for groundwood paper, so PBS refuses to build a groundwood cover rather than guess.

### 8. Preflight
Every export stores a report beside its file (`<file>.report.json`) and in the `publication` row. Statuses:
- pass, warn, fail;
- manual: a person must check, for example in KDP's previewers or against the cover template;
- unavailable: the tool is not installed.

**Interior PDF:** page size against trim, page count against the trim/ink/paper range, gutter for the page count, other margins, embedded fonts (subsetting noted), effective image DPI, language tag, annotations, bookmarks, encryption, file size, blank-page runs, minimum text size, code lines wider than the text block, equations printed as source, cross-references.

**EPUB:** mimetype and container, required metadata, manifest, navigation, well-formed XHTML, internal links and fragments, alt text, accessibility metadata. **EPUBCheck** runs if `epubcheck` is on PATH or `PBS_EPUBCHECK_JAR` and Java exist; otherwise it is "unavailable" and never "pass". Kindle Previewer is a manual step.

**DOCX:** package parts, well-formed XML, opens in python-docx, picture alt text.

**Covers:** single page, exact size for the page count, artwork rights and DPI, spine text, the barcode area (manual), colour (manual), and a printer check against KDP's template (manual).

**eBook cover:** pixel size, ratio and file size.

**Metadata:** title + subtitle length and wording, author, description rules, keywords (count, promotional words, repeats of the title or author), categories (manual, unverified), age range, and AI disclosure. PBS also counts the chapter revisions made from accepted AI suggestions.

Every report states that passing does not guarantee KDP acceptance.

### 9. The publish package
`POST /publishing/package` builds all five formats, the covers from that PDF's page count, and these files:
- `metadata.json` and `metadata.txt`;
- `preflight-report.json` and `.html`;
- `COPYRIGHT-AND-LICENSES.txt`, `SOURCES.txt` and `KDP-UPLOAD-STEPS.md`;
- `manifest.json`, with SHA-256 for every file and `auto_publish: false`.

They are written to `projects/<id>/publish/packages/<package>/<slug>/`, plus a ZIP. Nothing is sent anywhere. MOBI/AZW3 are not built: KDP takes EPUB, and no converter is installed. This is stated in the UI.

## Consequences and limits
- DOCX equations are LaTeX text, not Word equations. Word users must convert them, and Word's own TOC field must be updated.
- PDFs are standard tagged PDF, not PDF/X-1a, and colours are RGB. KDP accepts these, but a printed proof is the real check.
- Fonts are embedded as subsets. KDP recommends full embedding but accepts embedded fonts; this is reported as a warning.
- No live web verification: preflight never contacts KDP or any web page, and links are checked by form only.
- The LaTeX → Typst converter covers a subset. Other equations print as LaTeX source and are reported.
- Hardcover covers, interior bleed and spot colours are not supported.
