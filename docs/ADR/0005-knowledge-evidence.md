# ADR-0005: Knowledge sources, citations and the evidence ledger

Status: Accepted (Phase 04, 2026-11-22).

## Context
Phase 04 lets the author bring in reference material and have AI suggestions draw on it. The rules that shaped it:
- cite by exact passage;
- never fabricate titles, URLs, page numbers or DOIs;
- keep evidence separate from prose;
- treat all source text as untrusted (prompt injection);
- a disabled source must not reach new generations;
- citations must survive backup and restore.

## Decisions

### 1. Sources are originals plus derived, anchored passages
**Import.** An import reuses the Phase 02 importers and their safety checks: archive limits, XXE, encrypted and scanned files, HTML reduced to safe structure. The original bytes go into the shared, immutable `original_file` store. The text is split into **paragraphs with anchors**:
- a heading path;
- paragraph numbers;
- for PDFs, page numbers from the file's own page order.

**Chunks.** Paragraphs are grouped into chunks of about 1,200 characters. A chunk never crosses a heading, or a page in a PDF, so a citation like "p. 3" is exact. Chunks are derived and can be rebuilt ("Re-read file").

**Text.** Knowledge text is the source's literal text. Markdown escapes added by the importers are removed outside code, so quotes match the source.

**Titles and metadata.** The title comes from the PDF's own metadata or the file name, and the UI says which. Authors, year, publisher, URL and DOI are only ever what the author types; the DOI and URL formats are validated.

**Deduplication**, per library:
- the same file bytes are refused;
- the same normalized text is refused unless the author chooses "Add it anyway". A partial unique index backs the same-file rule.

**Removal** is soft. Chunks and index rows are deleted. A tombstone source row stays so ledger quotes keep their title. The original file is kept.

### 2. Search: SQLite FTS5, explained
`source_chunk_fts` is an FTS5 table over passage text, heading and title, using `unicode61 remove_diacritics 2` and bm25 weights 1/2/2.

**Query handling.** User input is reduced to word tokens and each is quoted, so FTS syntax cannot be injected. Search first requires every word; if nothing matches, it falls back to any word and says so.

**Results.**
- Highlights come back as `{text, hit}` segments, never HTML, so the UI renders source text as text.
- Each hit lists its **match reasons**: which words were found in the passage, heading or title, and which were not.
- Semantic (embedding) search is a capability flag reported as `unavailable`; no local embedding model is set up yet.

### 3. Who may use which source
Two kinds of library:
- **book libraries**, owned by one book;
- **shared libraries**, which a book uses only after the author opts in.

Only sources that are enabled, indexed and not removed are eligible. **Retrieval runs when the job runs**, not when it is queued, so disabling a source stops it reaching the next generation even if a request was already waiting. This is tested.

### 4. Source-aware prompts and citation checking
The job takes up to 6 passages (12,000 characters) from the book's eligible sources, chosen by FTS over the instruction, the selection (or the end of the chapter) and the chapter title.

**Prompt format.** Each passage gets its own random-tag envelope, labelled S1…Sn with its title and locator. Interview answers are labelled I1…In. Any envelope-like text inside untrusted material (`<pbs-data…`) is neutralised. The model is told to:
- put `[[S2]]` after any sentence that uses a passage;
- use only the labels shown;
- never invent titles, authors, pages, URLs or DOIs.

**Checking the output** (`knowledge/citations.py`):
- **Unknown labels** are dropped and reported. The UI says "the model cited passages it was never given; those citations were removed."
- **Located vs not located.** Each cited sentence is matched against its passage by content-word overlap. The best-matching sentence of the passage becomes the **quote**. A weak match is flagged "not located".
- **Paragraph status.** Each paragraph is `supported`, `not_located` or `unverified` (no citation). The review pane shows the passages behind each paragraph, or an explicit "Unverified" flag.
- **Rewriting markers.** Source labels become BookMD citations `[@key, p. 3]` with the source's stable key and a locator it really has. Interview labels are removed from the prose; the ledger keeps the link to the exact answer.

**Defence in depth.** The model has no tools and its output is only a proposal. Citations can only reference passages that were sent, and they are verified against the passage text.

### 5. Evidence ledger, separate from prose
The ledger has two tables:
- `claim`: text, origin, lifecycle `proposed → in_text | discarded`, the author's review state, and support status;
- `claim_support`: a copied quote, citation key, locator, `located`, and links to the source, chunk or interview answer.

**AI claims** are created with the proposal. They become `in_text` when the suggestion is accepted and `discarded` when it is rejected. **The author can add claims** and pick supporting passages from search; a passage from a source the book cannot use is refused.

Because evidence is copied, it survives re-indexing (supports are re-linked by quote) and removal of its source (marked "source removed").

`GET /projects/{id}/citations` exports bibliographic metadata, CSL-JSON-like, for the sources actually cited in the text. It includes only known fields.

### 6. Citation keys are stable and book-scoped
A key comes from the first significant words of the title, with a numeric suffix on collision, and never changes, even when the title is edited. Uniqueness is `UNIQUE(key_scope, citation_key)`, where the scope is the owning book or `shared`. A restored book therefore keeps exactly the keys its chapters cite, with no text rewriting.

### 7. Author voice: local analysis, editable guide
Samples:
- require an explicit rights confirmation, "own writing" or "licensed" (API check plus DB CHECK);
- are de-duplicated per profile.

The analysis is deterministic and local: sentence-length statistics, contractions, person, questions, punctuation habits, vocabulary variety, Flesch reading ease, frequent openers. Labels such as "conversational" are shown as heuristics.

Examples are **exact excerpts** from the samples. The drafted style guide is editable; once edited, re-analysis never overwrites it. The author can also add before/after **corrections**.

"Rewrite in a voice" is the revise task with a `voice_profile_id`: the guide, examples and corrections go in a style-reference envelope. The result is a normal proposal, shown before/after and applied only on Accept. The earlier revision stays in History.

Using `revise` with a voice avoids changing the task CHECK constraints on `job` and `task_route`; the template is recorded as `revise+voice@…`.

### 8. Interview-to-book
- A built-in bank of ten questions, plus the author's own.
- Answers are stored verbatim with time and method. They are **immutable** (DB triggers); changing an answer stores a new version that supersedes the old one.
- Prompts with answers tell the model to use only experiences in them. Prompts without answers tell it never to invent personal experiences, but to leave a bracketed note instead.

### 9. Backup and restore
A book backup now includes:
- its libraries, plus the shared libraries it uses, restored as the copy's own libraries;
- sources (including tombstones), chunks and their originals;
- non-discarded claims with their supports;
- the interview with all answer versions.

On restore, keys are preserved and the FTS index is rebuilt. Voice profiles are workspace-wide and not part of a book backup.

**Fixed along the way:** restoring AI-origin revisions into the same workspace violated the "proposal applied once" index. Restored revisions now get a new, consistent opaque proposal reference; proposals and jobs are not backed up.

## Consequences and limits
- Locating is lexical. A paraphrase with few shared words is flagged "not located" even if it is faithful, and the author decides. Semantic matching would need embeddings (a future capability).
- Only one chapter's worth of passages is retrieved per request. There is no cross-chapter planning yet (Phase 05).
- Chapter preview renders citations as `(key, locator)`, not as links. The review pane, ledger and source viewer link to passages.
- No OCR: scanned PDFs are recorded as failed sources with the reason.
