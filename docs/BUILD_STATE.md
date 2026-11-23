# Personal Book Studio — Build State

> Single source of truth for "where are we". Every phase ends by updating this file with **evidence** (commands + real results).

## Current status

| Field | Value |
|---|---|
| Current phase | **05: Project planning (wizard, brief, research, outline, skeleton, generation runs): COMPLETE (pending user review)** |
| Next phase | 06 |
| Branch | `phase/05-planning`, stacked on `phase/04-knowledge` (PR #4), then Phase 03 (PR #3), Phase 02 (PR #2) and Phase 01 (PR #1). Nothing merged yet. Phase 05 is not committed yet |
| Schema | Alembic head `0006` (`0006_planning`). The dev workspace migrated 0005 → 0006 automatically, with a snapshot |
| Platforms verified | Windows 11 x64 only. macOS is **not executed** |
| Last updated | 2026-11-22 |

## Phase 05 evidence (real results, 2026-11-22, Windows 11, CPython 3.12.13, Node 26.13)

Command: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1` → **exit 0, "All checks passed."**

| Check | Result |
|---|---|
| ruff lint / format (Core) | All checks passed / 129 files already formatted |
| mypy `--strict` (98 source files) | Success: no issues found |
| import-linter | 4 kept, 0 broken (the Open Library client lives in `pbs_core.providers`, behind the egress gate) |
| pytest (Core) | **228 passed, 1 skipped, 3 xfailed**. The skip is the Ollama smoke test (no local Ollama). The xfails are golden steps owned by Phase 07. Step 05 now passes |
| License gate | passed: 94 runtime dependencies (no new dependencies; Open Library is called with the existing `httpx2`) |
| ESLint (jsx-a11y strict) + Prettier, TypeScript strict | clean |
| Vitest + RTL + axe-core | **37 passed** (9 files; 2 new: `lib/outline.test.ts`, `Plan.test.tsx`) |
| Vite production build | built |
| Playwright + axe (WCAG 2.2 AA tags) | **13 passed** (2 new specs in `planning.spec.ts`) |

### Prompt 05 acceptance → evidence

| Acceptance item | Where it is proven |
|---|---|
| From a new idea, build and approve a detailed outline with a deterministic test adapter, without paid API access | pytest `test_idea_to_approved_outline_with_test_model` and golden step 05. Playwright "Phase 05 acceptance": New Book wizard → brief (prefilled from the wizard) → Approve brief → AI outline proposal from the built-in test model → Approve → Apply → three planned chapters. No API key exists in the test run, and the egress counter stays at zero |
| Unsupported market metrics are never fabricated | `test_ai_brainstorm_cannot_carry_market_metrics`: the test model is made to claim sales rank, search volume and "bestseller" status (`[[mock:metrics]]`). Every such sentence is removed and flagged, and an item that was only a claim is dropped. Writing `metrics_json` on an AI row, or marking an AI finding measured, is refused **by DB CHECK constraints**. Also `test_ai_finding_cannot_become_measured`, `test_author_findings_separate_measured_from_heuristic` (an unsourced figure the author types is flagged `unsourced_metric` and shown as opinion), and `test_open_library_results_keep_bibliographic_data_only` (reading-log and rating fields are never requested or kept) |
| An approved outline becomes a durable chapter skeleton; a changed outline does not destroy prose or revision history | `test_changed_outline_keeps_prose_history_and_locks`: write prose → rename, move and remove nodes → approve v2 → apply. The chapter with prose is renamed with its text and revisions intact, the removed chapter with prose is **kept** and reported, the empty one is archived, and the locked one is untouched. `test_ai_regeneration_never_overwrites_draft_and_keeps_locked`. Playwright: prose and History survive a rename and a removal |
| Fail-safe behaviour on an unavailable research provider is explicit | `test_research_provider_off_blocked_or_down_fails_explicitly`: off → 409 `research_unavailable` with reason `not_configured`; local-only mode → `blocked` (zero egress); provider outage → `failed`. Each says nothing was searched or added, adds no findings, and is logged in `research_query`. Playwright: the Research tab shows "… is not turned on. Nothing was searched" and the measured list stays empty |

### Other Phase 05 requirements → evidence

| Requirement | Evidence |
|---|---|
| New Book wizard with all requested fields | `NewBookPage.tsx` (four steps); `test_wizard_creates_book_brief_and_links_sources`; Playwright (axe clean) |
| Research workspace: topic finder, query drafting, providers only when configured, editable findings with source/date/URL, competitor notes, KDP keyword brainstorming | Research tab; `POST …/research/ideas` (topics, queries, keywords, each flagged `ai_brainstorm_not_measured`, keywords also `no_search_volume_data`); `PATCH …/findings/{id}`; "Save as comparable title" copies from the server-side query log |
| Heuristic observations kept apart from measured evidence | API `evidence` field ("measured" / "heuristic"); two separate UI regions; DB CHECK: measured ⇒ named source |
| Brief with target reader, promise, exclusions, value proposition, teaching or plot arc, explicit assumptions | Brief tab; `test_brief_approval_and_new_version_on_change` |
| Outline: stable IDs, drag-reorder, merge/split, hierarchy, chapter goals, target words, estimated writing work | `lib/outline.ts` + Vitest (IDs kept on move, merge keeps the first ID, split, nest/un-nest, locked entries never merged or split); server validation `test_outline_structure_is_validated`; totals with hours labelled as estimates |
| Approval before any bulk generation | `test_bulk_generation_requires_an_approved_applied_outline` |
| Nonfiction source/citation requirements; fiction plot, character and continuity requirements | Per-node `requirements` in the outline; `requirements_check` stored with each chapter proposal (citations found vs required, characters named; plot and continuity marked "review yourself") |
| Cost and time previewed as estimates; hard budget cap; chapter limit | `test_budget_cap_blocks_and_stops_runs` (unknown cost, currency mismatch and over-cap estimate refused; reaching the cap mid-run cancels the queued chapters), `test_chapter_limit_blocks_large_runs`; Playwright estimate table ("Local model: no API charge") |
| Outline-first, one-chapter and entire-book modes honour manual edits and locks | `test_entire_book_honours_prose_locks_and_review` (locked, approved, unsaved-draft and prose chapters skipped with reasons; output is proposals only). Playwright: "Every eligible chapter" → suggestions wait for review and nothing is written |
| Backup | `test_backup_restore_keeps_brief_findings_outlines_and_links` |

## Phase 05: what was built

**Core**
- Migration `0006_planning`: `book_brief`, `research_finding` (with the metric and measured-source CHECKs), `research_query`, `outline_version` (one approved per book, partial unique index) and `generation_run`. `migrations/env.py` now excludes the FTS5 shadow tables from autogenerate.
- `planning/`:
  - `outline.py`: tree validation (part > chapter > section, at most 500 nodes), stable `n_<ULID>` IDs, totals, keeping locked nodes;
  - `skeleton.py`: applies an approved outline to chapters without touching prose;
  - `research.py`: the market-metric guard;
  - `runs.py`: the budget stop and requirement checks.
- `providers/research_adapters.py`: the Open Library adapter (bibliographic fields only, generic User-Agent, `openlibrary.org` on the egress allowlist) and a dev/test catalogue that can simulate an outage.
- Planning jobs (`outline`, `research_ideas`) on the existing job runner: `jobs/planning_prompts.py` (schemas, "no market data" rule) and `jobs/planning_exec.py`. Chapter drafting from the outline uses the normal chapter job path with run, node and requirements context; each finished chapter records its actual cost against the run.
- `services/planning.py` and `api/routes_planning.py`: 23 new endpoints (102 API paths in total), including `POST /api/books` for the wizard.
- Backup includes the brief, findings and every outline version.

**UI**
- **New book** wizard: the project form plus "Reader and promise", "Shape and sources" and "Approvals and budget".
- **Plan** page per book, with four tabs:
  - **Brief**, with approve and versioning;
  - **Research**: measured evidence, notes and ideas (heuristic), public catalogue search, and AI brainstorm;
  - **Outline**: the AI proposal with approve, edit or reject; your draft, with drag handles, Up/Down/Indent/Outdent, merge, split, add, remove, lock, goals and requirements; the approved outline with "Apply to manuscript" and an apply report;
  - **Draft chapters**: one chapter or every eligible chapter, an estimate table, then runs with status and Stop.
- **AI settings**: a "Research search" section to turn Open Library on (needs cloud allowed).
- Navigation: Research is no longer "not implemented"; the book page links to Plan.

**Docs:** ADR-0006; SECURITY §7d; DATA_MODEL §2.3b; ARCHITECTURE §7.3; TEST_PLAN §4.4b; README "Planning a book (Phase 05)".

## Decisions taken in Phase 05 (need your validation)

| # | Decision | Why | Reversible? |
|---|---|---|---|
| P5-1 | Outline sections stay inside their chapter (as `##` headings); only parts and chapters become chapter rows | One document per chapter; no tiny section documents | Yes |
| P5-2 | Open Library is the only real research provider, off by default, and it needs `cloud_allowed` | Free and keyless, with bibliographic data only; no licensed market-data source exists | Yes, add adapters behind the egress gate |
| P5-3 | Time estimates come only from this workspace's measured throughput; otherwise "unknown" | No guessed speeds | Yes |
| P5-4 | An unknown cost blocks a run when a budget cap is set (before and during the run) | A cap that cannot be checked is not a cap | Yes |
| P5-5 | Entire-book mode skips chapters that already have text; one-chapter mode may append to one | Bulk runs never pile onto your prose | Yes |
| P5-6 | Metric statements in AI brainstorms are removed (and flagged), not just labelled | "Never fabricate" is stronger than "label as fabricated" | Yes |
| P5-7 | The brief's kind is derived from the project type (fiction/serial → fiction; course/technical → manual) | One source of truth | Yes |
| P5-8 | Every drafted chapter is a proposal, whatever the approval preference | "AI never silently overwrites" | Yes (a batch-accept could come later) |

## Known limitations (Phase 05, honest list)

1. **No licensed market data.** Sales rank, demand, competition and search volumes are "not available" by design.
2. **Plot points and continuity are not machine-checked**; the requirement check marks them "review yourself".
3. **Outline generation is one model call.** Very long books depend on the model's output limit.
4. **The first run on a model always shows "time unknown"** (no throughput history yet).
5. **Research query logs and generation runs are not backed up** (findings, briefs and outlines are).
6. Open Library was not called live (the adapter is tested through a mock transport with its documented response shape and a simulated connection failure; the socket guard forbids real network in tests).
7. Real Ollama and cloud models remain unexercised here (see Phase 03).
8. My visual check opened a hand-written outline draft on "The Quiet Engine" in the dev workspace but did not save it, so nothing was added.

## Phase 05: bugs found and fixed

- **Alembic autogenerate tried to drop the FTS5 tables** from Phase 04. They are now excluded in `migrations/env.py`.
- **The dollarmath plugin crashed on text ending in a backslash** (its escape check read `src[-1]`). Patched in `bookmd.py`, with a regression test.
- **Nested-transaction deadlock** when listing research providers inside a request transaction. It now reads in the same session.

## Phase 06 handoff

Preserve:
- outline node IDs and `chapter.outline_node_id` as the link between plan and manuscript;
- the skeleton rules (never touch prose; keep, don't delete, chapters with text);
- proposals as the only way AI text reaches a revision;
- the budget stop in `runs.record_cost` and the run's skip reasons;
- the market-metric guard and the measured/heuristic split;
- research only through the egress gate, failing explicitly.

Start Phase 06 from `generation_run` and the per-node requirements: they are the natural inputs for multi-step chapter jobs (`job_step`, deferred since Phase 03) and for continuity checks across chapters.

---

## Phase 04 evidence (real results, 2026-11-22, Windows 11, CPython 3.12.13, Node 26.13)

Command: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1` → **exit 0, "All checks passed."**

| Check | Result |
|---|---|
| ruff lint / format (Core) | All checks passed / 115 files already formatted |
| mypy `--strict` (86 source files) | Success: no issues found |
| import-linter | 4 kept, 0 broken |
| pytest (Core) | **210 passed, 1 skipped, 4 xfailed**. The skip is the Ollama smoke test (no local Ollama). The xfails are golden steps for Phases 05 and 07. Step 04 now passes |
| License gate | passed: 94 runtime dependencies (no new dependencies: FTS5 ships with SQLite, and voice analysis uses the standard library) |
| ESLint (jsx-a11y strict) + Prettier, TypeScript strict | clean |
| Vitest + RTL + axe-core | **29 passed** (7 files; 5 new) |
| Vite production build | built |
| Playwright + axe (WCAG 2.2 AA tags) | **11 passed** (2 new knowledge specs) |

### Prompt 04 acceptance → evidence

| Acceptance item | Where it is proven |
|---|---|
| Imported sources are searchable, cited by exact passage and removable | pytest: `test_import_preserves_original_and_records_anchored_chunks`, `test_pdf_passages_carry_page_numbers` ("p. 3"), `test_search_highlights_exact_passage_with_reasons`, `test_remove_and_reindex`, golden step 04. Playwright `knowledge.spec.ts`: import → search with `<mark>` → open the cited passage (highlighted) → cite → remove → search finds nothing, and the ledger quote shows "source removed". Also checked by hand in the desktop browser pane (highlighted hits with locator and match reasons) |
| Disabling a source prevents its use in new generations | `test_disabling_a_source_keeps_it_out_of_new_generations`: disabled **after queueing** and **before running** → the prompt has no passage, provenance lists no source, every paragraph is "unverified"; re-enabling restores it. Playwright: "Use for AI" off → "No source passages will be sent" → the card has no source links |
| A generated paragraph shows supporting sources or an explicit "unverified" flag | `test_generated_paragraphs_show_sources_or_unverified`: per-paragraph `supported` with key, locator and an exact quote found in the source, plus a trailing `unverified` paragraph; the text gets `[@torque-handbook, para. N]`. `test_fabricated_citation_is_dropped_and_flagged`. Vitest "Sources on a suggestion" (links to the passage, "Unverified" flag, removed-citation warning). Playwright |
| Style rewrite is preview-only until accepted; the original revision stays accessible | `test_style_rewrite_is_preview_only_until_accepted`: the chapter stays at revision 1 until Accept; afterwards `GET …/revisions/1` returns the original text; the proposal shows before/after (replace mode) |
| Tests cover provenance, injected malicious text, deduplication, backup/restore of citations | provenance (above); injection: `test_malicious_source_text_stays_data`, `test_forged_envelope_in_plain_text_source_is_neutralised`; deduplication: `test_deduplication_by_file_and_by_text`; backup/restore: `test_backup_restore_keeps_citations_sources_claims_and_answers` (same chapter text and `[@key]`, citations resolve, 2 claims with supports and quotes, search index rebuilt, interview answer kept, original book untouched) |

### Other Phase 04 requirements → evidence

| Requirement | Evidence |
|---|---|
| Per-book and shared opt-in libraries; tags, enable/disable, remove/re-index, indexing status | `test_books_only_see_their_own_and_opted_in_sources`, `test_unreadable_source_is_recorded_as_failed`; UI Sources, Knowledge and source pages |
| Chunks with headings and page/paragraph anchors; provenance; originals preserved | ADR-0005 §1; tests above |
| FTS5 search, highlighted passages, transparent match reasons; semantic search behind a capability flag | `search.py`; the API reports `semantic: "unavailable"` with a note (no embedding model) |
| Never fabricate titles, URLs, pages or DOIs | Titles from file metadata or name, labelled; bibliographic fields author-entered only (`test_source_metadata_is_only_what_the_author_enters`); locators only from real anchors; invented labels dropped |
| Evidence ledger separate from prose, with review state and stable keys; export of citation metadata | `claim` / `claim_support` tables, the Evidence page, `test_author_claims_link_to_exact_passages`, `GET /projects/{id}/citations` |
| Author voice: own writing only, analysis, editable guide, before/after, corrections | `test_samples_require_rights_confirmation`, `test_analysis_metrics_examples_and_editable_guide`, Vitest voice test, Playwright |
| Interview: exact answers with provenance; never invent experiences | `test_answers_are_exact_versioned_and_immutable` (DB trigger), `test_drafting_from_interview_uses_only_the_authors_words` |
| Injection isolation; escape external HTML | ADR-0005 §4, SECURITY §7c, the tests above, the Vitest search test (a `<script>` in a snippet renders as text) |

## Phase 04: what was built

**Core**
- Migration `0005_knowledge`: `knowledge_library`, `library_link`, `source`, `source_chunk`, the FTS5 table `source_chunk_fts`, `claim`, `claim_support`, `author_profile`, `voice_sample`, `interview_session`, `interview_question`, and `interview_answer` with immutability triggers.
- `knowledge/`:
  - `extract.py`: anchored paragraphs and chunks; never crosses a heading or a PDF page;
  - `search.py`: FTS5, safe queries, plain-text highlight segments, match reasons;
  - `retrieval.py`: eligible sources and answers, chosen at run time;
  - `citations.py`: checks markers, locates quotes, rewrites to `[@key, locator]`, gives per-paragraph status;
  - `voice.py`: deterministic style analysis.
- Services:
  - `knowledge.py`: libraries, import with dedupe, patch, remove, re-index, viewer, search, citation export;
  - `evidence.py`: the ledger;
  - `voice.py`;
  - `interview.py`, with a 10-question bank;
  - `backup_knowledge.py`.
- AI integration:
  - prompts carry passage, answer and style envelopes with neutralisation and citing rules;
  - the executor retrieves at run time, processes citations and records ledger claims in the proposal transaction;
  - accept/reject moves claims to in-text or discarded;
  - requests take `use_sources`, `use_interview` and `voice_profile_id`;
  - the estimate shows how many passages and answers will be sent.
- The test model cites provided passages and simulates a fake citation and a compromised model (`providers/mock_knowledge.py`).
- `api/routes_knowledge.py`: 31 new endpoints.

**UI**
- **Book → Sources**: add files (duplicate notice with "Add it anyway"), the source list with status, tags, "Use for AI", "Re-read file" and Remove, a search with `<mark>` highlights, locators and "why it matched", and shared-library opt-in.
- **Knowledge** (menu): shared libraries.
- **Source page**: passages with locators, the cited passage highlighted and focused, and author-entered bibliography fields.
- **Evidence ledger**: claims with support status, exact quotes linked to passages, review state, add-a-claim with a passage picker, and the cited-sources list.
- **Interview**: questions with verbatim answers, version history, your own questions, and a third-party consent note.
- **Author voice**: profiles, samples behind a rights checkbox, heuristic measures, exact example sentences, an editable style guide, and before/after corrections.
- **AI assist**:
  - choose whether to use the book's sources and the interview;
  - "Rewrite in a voice" when revising;
  - the estimate shows the passages to be sent;
  - suggestion cards show the passages behind each paragraph, "Unverified" flags, and a removed-citation warning.
- Navigation: Knowledge and Author voice are live. The book page links to Sources, Evidence ledger and Interview.

**Docs:** ADR-0005; SECURITY §7c; DATA_MODEL §2.3a; ARCHITECTURE §7.2; TEST_PLAN §4.4a; README.

## Decisions taken in Phase 04 (need your validation)

| # | Decision | Why | Reversible? |
|---|---|---|---|
| P4-1 | Lexical (FTS5) search only; semantic search reported as unavailable | No local embedding model is set up; never pretend | Yes, add embeddings via Ollama later |
| P4-2 | Citation "located" means lexical overlap ≥ 25% (at least 2 content words) with a sentence of the cited passage | Deterministic, explainable; a weak match is flagged, never hidden | Yes, tune the threshold |
| P4-3 | Retrieval happens when the job **runs**, not when it is queued | So disabling a source always takes effect | Yes |
| P4-4 | Citation keys are scoped to a book (or "shared") and never change | Restore keeps the keys without rewriting text | Costly later |
| P4-5 | A style rewrite is `revise` with a voice profile, not a new task | Avoids changing job/route CHECK constraints | Yes |
| P4-6 | Paragraphs without citations are always labelled "Unverified", even in fiction | The brief requires an explicit flag; wording is neutral | Yes (could hide for fiction) |
| P4-7 | Removing a source keeps a tombstone row and the original file | Ledger quotes keep their title; originals are immutable | Yes |
| P4-8 | Voice profiles are workspace-wide and not in book backups | They belong to the author, not a book | Yes |

## Known limitations (Phase 04, honest list)

1. **No semantic search** (capability flag `unavailable`). Synonyms and paraphrases are not found.
2. **Locating is lexical.** A faithful paraphrase that shares few words is flagged "not located"; the author decides.
3. Retrieval picks at most 6 passages (12,000 characters) per request from one query. There is no multi-step research (Phase 05).
4. **Chapter preview shows citations as `(key, locator)` text, not links**; links to passages live in the review pane, ledger and source page.
5. **No OCR**: scanned PDFs become failed sources with the reason. PDF headings are guessed from "Chapter …" lines only.
6. **No bibliography rendering yet.** Citation metadata is exported as JSON for Phase 07.
7. Interview questions come from a fixed bank plus the author's own. AI-suggested follow-up questions are not built.
8. **The voice analysis is English-centric** (reading ease, contractions).
9. Real Ollama and cloud models remain unexercised here (see Phase 03).
10. My visual check added a source ("torque-handbook") to "The Quiet Engine" in the dev workspace (`.pbs-data`, git-ignored). Remove it on that book's Sources page if unwanted.

## Phase 04: bugs found and fixed

- **Phase 03 restore bug:** restoring AI revisions into the same workspace violated the "proposal applied once" unique index. Restored revisions now get a new, consistent reference. Found by the citation backup test.
- **Importer output was Markdown-escaped** (`\[\[S7\]\]`, `\<`), which corrupted quotes and hid injected markers. Knowledge text is now the source's literal text.
- **A three-page PDF became one chunk citing "pp. 1–3".** Chunks now break at page boundaries.
- **Restore inserted interview questions before their session** (no ORM relationships). Parent rows are now flushed first.
- **Source action buttons stretched to full row height** (visual check).

## Phase 05 handoff

Preserve:
- retrieval at run time and the eligibility rules;
- envelopes and neutralisation for all untrusted text;
- citations only from provided labels, rewritten to stable keys;
- the ledger's copied quotes;
- immutable interview answers;
- the "unverified" flag.

Start Phase 05 with: the book brief and outline versions using the ledger and sources as research inputs; research findings stored as ledger claims with `kind` and provenance; and multi-query retrieval per outline node.

---

## Phase 03 evidence (real results, 2026-11-22, Windows 11, CPython 3.12.13, Node 26.13)

Command: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1` → **exit 0, "All checks passed."**

| Check | Result |
|---|---|
| ruff lint / format (Core) | All checks passed / 97 files already formatted |
| mypy `--strict` (71 source files) | Success: no issues found |
| import-linter | **4 kept**, 0 broken. New: network clients (`httpx2`, `openai`, `anthropic`, …) only inside `pbs_core.providers` |
| pytest (Core) | **186 passed, 1 skipped, 5 xfailed**. The skip is the Ollama smoke test (no local Ollama on this machine). The xfails are golden steps owned by Phases 04, 05 and 07. Steps 06, 07 and 15 now pass |
| License gate | passed: 94 runtime dependencies (adds `anthropic` MIT, `openai` Apache-2.0, `keyring` MIT, `httpx2` and their dependencies) |
| ESLint (jsx-a11y strict) + Prettier, TypeScript strict | clean |
| Vitest + RTL + axe-core | **24 passed** (6 files; 6 new AI tests) |
| Vite production build | built |
| Playwright + axe (WCAG 2.2 AA tags) | **9 passed** (2 new AI specs against a loopback Ollama stub) |

### Prompt 03 "done when" → evidence

| Requirement | Where it is proven |
|---|---|
| Choose a local model, draft a paragraph into a review pane, accept → chapter revision | Playwright `ai.spec.ts` "Phase 03 acceptance". In the UI: add Ollama (stub server on 127.0.0.1) → Test connection → Find models → open a chapter → AI assist → pick `stub-writer:1b` → Ask → suggestion card (chapter unchanged) → Accept → revision 2, History shows "AI-generated (accepted)". Also checked by hand in the desktop browser pane with the built-in test model |
| Cancel/retry and restart do not corrupt the chapter or double-apply | Playwright `ai.spec.ts` "cancel, retry and a Core crash…": cancel mid-stream → no suggestion; Retry; **hard-kill Core mid-stream** → restart → exactly one suggestion; a **double-clicked Accept** creates one revision. pytest: `test_process_restart.py::test_ai_job_survives_hard_kill_without_double_apply` (real process), `test_restart_recovers_running_jobs_without_double_commit`, `test_cancel_while_streaming_applies_nothing`, `test_database_refuses_applying_a_proposal_twice` (unique index), `test_rate_limit_is_retried_with_backoff` |
| Local-only mode makes zero external AI calls | `test_local_only_mode_makes_zero_external_calls`: with a cloud provider configured and a key stored, test connection, model refresh, estimate and enqueue all refuse **before** the transport is called; the egress counter and the session socket guard both read zero. Golden step 15 (full draft → accept run). The AI settings page shows "Requests sent to the internet since Core started: none" (asserted in Playwright) |
| Automated tests pass | above |

### Other Phase 03 requirements → evidence

| Requirement | Evidence |
|---|---|
| Adapters for Ollama, OpenAI, Gemini, Anthropic, Grok (and Groq); endpoints verified, not guessed | ADR-0004 §2, with the facts verified against the official docs on 2026-11-22 and the unverifiable ones listed. Contract tests per adapter over recorded wire formats (`test_ai_providers.py`): request shape (`max_completion_tokens`, `stream_options`, no `temperature` for Claude, Gemini key in a header), streaming, usage, structured output, refusals, error mapping (quota vs rate limit vs auth, `Retry-After`), Ollama mid-stream errors |
| Keys in the OS credential store; dev fallback with warning; never in DB/logs/Git/exports/backups | `security/secrets.py` (keyring default; `dev-file` opt-in with warning). `test_api_key_never_leaves_the_credential_store` scans the DB, WAL, logs, backup ZIP and entries, and exports for a canary key → 0 hits. The API never returns the key, and a 422 on a bad key does not echo it |
| Task routing; explicit selection wins; no silent fallback | `test_task_route_is_used_and_estimate_is_labelled`, `test_no_model_chosen_is_an_explicit_error`; revoking consent fails a queued job with `egress_blocked` without sending anything |
| Structured JSON with validation; capabilities checked, not assumed | Native schema only when the capability is reported, documented or declared. `test_structured_brainstorm_is_validated` (bad JSON → retried → `invalid_output` after 3 attempts) |
| Estimate before running; actual usage; "estimate" and "unknown" labels | `costs.estimate`; `test_cloud_needs_confirmation_and_project_consent` (no price → `null` "Unknown", then priced → `0.000038 USD` from reported usage); Vitest jobs page ("Unknown", no `%`) |
| Durable queue: IDs, stages, retries, provenance, recovery, cancellation, bounded concurrency | `jobs/runner.py` + `jobs/execute.py`; the tests above plus `test_recover_marks_exhausted_jobs_interrupted` |
| Status center with logs, retry, actionable failures, cost table | `/jobs` page (Vitest + Playwright, axe clean) |
| Project-scoped requests, content limits, user review | One chapter per request, clipped to 48,000 characters; unsaved drafts and approved chapters block (`test_unsaved_changes_block_requests_and_accepts`, `test_approved_chapter_blocks_requests_and_accepts`); stale replace (`test_replace_selection_goes_stale_when_passage_changes`) |
| Mock adapter for CI; Ollama smoke test when available; live cloud opt-in | `providers/mock.py` (deterministic, labelled "not AI"); `test_ai_live.py::test_ollama_smoke` (`-m ollama`, skipped here); `python -m pbs_core.live_check` (never run by tests) |

## Phase 03: what was built

**Core**
- Migration `0004_ai_jobs` adds these tables: `provider_config`, `model_info`, `task_route`, `model_price`, `cloud_consent`, `job`, `job_log`, `proposal`, `usage_record`. It also adds `usage_record` immutability triggers and a partial unique index on `chapter_revision.accepted_proposal_id`.
- `providers/`:
  - `egress.py`: the gate, the external-request counter and live cloud activity;
  - `base.py`: neutral types and error classification;
  - adapters `mock`, `ollama`, `openai_compat` (OpenAI, Groq, xAI), `anthropic_adapter` and `gemini`;
  - `registry.py`: permits, key lookup, capability checks.
- `security/secrets.py`: keyring / dev-file / memory / read-only stores.
- `jobs/`:
  - `prompts.py`: versioned templates, random-tag data envelope, brainstorm schema;
  - `runner.py`: claim, lease, recovery, cancel, bounded pool;
  - `execute.py`: build, call, stream progress, retry/backoff, one-transaction commit.
- `services/ai.py` covers privacy mode, providers, keys, test, models, routes, prices, consent, estimate, enqueue, jobs, proposals, accept/reject and usage. `services/costs.py` computes estimates and costs; it never invents a price.
- `api/routes_ai.py` adds 27 endpoints. The job runner starts and stops with the app.
- `live_check.py` is the opt-in real-provider check.

**UI**
- **AI settings** (replaces the "not implemented" page):
  - privacy mode, with a confirmation before allowing cloud and the count of internet requests;
  - providers with on-computer/cloud labels, key status, store/remove key, test connection, find models, models table with capability sources, add a model manually with a declared capability, turn off, remove;
  - default model per task, with temperature and max output;
  - prices with source and date.
- **AI assist** in the chapter editor:
  - task, model (default or explicit, labelled with where it runs), instruction, placement, max tokens;
  - an estimate shown before running;
  - an explanation when a request is blocked, with a one-click per-book consent when cloud is allowed;
  - a "save first" guard;
  - request status by stage, with Cancel and Retry;
  - a review pane: a proof-slip card with provenance, editable text, struck-through original for replacements, "Accept as a new revision" or Reject. Notes can only be dismissed.
- A banner says when suggestions are waiting.
- **AI jobs** status center: every job with stage, attempts, error, log, partial output, Cancel/Retry, and a usage and cost table with totals by currency.
- The privacy badge shows "Sending to …" during cloud calls.
- Navigation: AI jobs and AI settings are now live.

**Docs:**
- ADR-0004 (provider integration).
- As-built sections in SECURITY (§7b), ARCHITECTURE (§6.1, §7.1), DATA_MODEL (§2.3) and TEST_PLAN (§4.4).
- A README "Using AI" section and new `PBS_*` settings.

## Decisions taken in Phase 03 (need your validation)

| # | Decision | Why | Reversible? |
|---|---|---|---|
| P3-1 | Support **both** xAI Grok and Groq ("Grok" was ambiguous) | Both are cheap to add through the OpenAI-compatible SDK | Yes |
| P3-2 | Chat Completions for OpenAI, Groq and xAI (not the Responses API) | The one shape all three share; OpenAI still supports it; xAI calls it legacy | Yes; follow-up in ADR-0004 |
| P3-3 | Gemini via REST `generateContent` (legacy but supported), not the new Interactions API | Better-documented streaming and usage | Yes |
| P3-4 | `dev-file` key fallback (opt-in, warned), superseding SECURITY §3 "no plaintext file" | The Phase 03 brief asked for an explicit protected dev fallback | Yes |
| P3-5 | Ollama only on loopback; remote Ollama refused | A LAN server is not "local"; it has no allowlist entry | Yes, with consent rules |
| P3-6 | AI works only from the **saved** head; unsaved drafts block Ask and Accept | Provenance stays tied to an immutable revision, and a draft is never destroyed | Yes |
| P3-7 | Threads + SQLite claim instead of asyncio workers; single-step jobs (`job_step` deferred to Phase 06) | Simpler cooperative cancel with the sync SDKs | Yes |
| P3-8 | Stale proposals are computed when read; the "rebase" is "ask again" | No stored state to drift | Yes |
| P3-9 | No shipped prices; prices are per provider and model, entered by the author | "Do not guess" | Yes |
| P3-10 | The built-in test model is listed in dev/test only, labelled "not AI" | Lets the workflow be tried offline without misleading anyone | Yes |

## Known limitations (Phase 03, honest list)

1. **No real Ollama or cloud provider was exercised here.**
   - Ollama is not installed on this machine, and no API keys were used.
   - Adapters are tested against the documented wire formats, and the UI flow against a loopback Ollama stub.
   - Run `uv run pytest -m ollama` (with `PBS_OLLAMA_MODEL`) and `python -m pbs_core.live_check` to confirm against real services.
2. Facts not verifiable from the docs are listed in ADR-0004 ("Not verified"):
   - OpenAI Responses usage fields;
   - Gemini `RetryInfo` and pagination;
   - Groq streamed usage;
   - the xAI error format.
3. **The review pane has no word-level diff for "replace" suggestions.** It shows the struck-through original and the new text. Append and insert suggestions are pure additions.
4. Requests send **one chapter** (clipped to 48,000 characters). There is no cross-chapter or book-level context yet (Phases 05–06).
5. **Token estimates** use ~4 characters per token. They are labelled as estimates, and actual reported usage is recorded after each call.
6. Research is plain model knowledge with no web access, and the UI says so. Sourcing and citations arrive in Phase 04.
7. Cancelling a non-streamed Groq structured request takes effect after the response arrives, and the result is then discarded.
8. **The Windows credential store is used in dev runs** (`auto`). Tests and e2e use the in-memory store. The macOS Keychain is untested.
9. The `.claude/launch.json` preview needed two starts in the desktop browser pane.
10. My visual check left a "Built-in test model" provider, one job and one pending suggestion in the dev workspace (`.pbs-data`, git-ignored). Reject the suggestion or remove the provider in the app to tidy up.

## Phase 03: bugs found and fixed

- **Hypothesis found a Phase 02 serializer bug:** an attribute value ending in `\` escaped its closing quote. Backslashes are now entity-escaped, with a regression test.
- **Nested-transaction lock:** reading the privacy setting inside the request transaction deadlocked. It is now read in the same session.
- **The mock output was not deterministic:** the random envelope tag changed its hash.
- **E2E found that a job finishing in the background did not refresh the review pane.** The pane now invalidates when a job succeeds.
- **The instruction box inherited the 60vh editor height**, and a few labels were redundant (visual check).
- **Tests were order-dependent** on the process-wide egress counter. They now compare against a baseline.

## Phase 04 handoff

Preserve:
- the egress gate as the only network path (add allowlist entries, never bypass it);
- `registry.permit_for` and the per-project consent;
- prompts with data envelopes (`jobs/prompts.py`): extend `build()` with retrieved source chunks as **more envelopes**, never as instructions;
- proposals as the only way AI text reaches a revision;
- the unique index on `accepted_proposal_id`;
- the capability vocabulary;
- "unknown, not guessed" for prices.

Start Phase 04 with:
- the source library and chunk IDs that prompts can cite;
- dropping model-emitted citations that are not in the provided set (SECURITY §5.4);
- the prompt-injection fixture suite (§5.6) run through the mock adapter.

---

## Phase 02 evidence (real results, 2026-11-22, Windows 11, CPython 3.12.13, Node 26.13)

Command: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1` → **exit 0, "All checks passed."**

| Check | Result |
|---|---|
| ruff lint / format (Core) | All checks passed / 73 files already formatted |
| mypy `--strict` (51 source files) | Success: no issues found |
| import-linter | 3 kept, 0 broken |
| pytest (Core) | **135 passed, 8 xfailed** (8 = golden-path steps owned by Phases 03–07, strict xfail) |
| License gate | passed: 83 runtime dependencies (adds mammoth BSD-2, pypdf BSD-3, nh3 MIT, latex2mathml MIT, python-multipart Apache-2.0, defusedxml PSF, CodeMirror MIT) |
| ESLint (jsx-a11y strict) + Prettier, TypeScript strict | clean |
| Vitest + RTL + axe-core | **18 passed** (5 files) |
| Vite production build | built |
| Playwright + axe (WCAG 2.2 AA tags) | **7 passed** (2 new Phase 02 specs + 5 Phase 01 specs adapted to the new editor) |

### Prompt 02 acceptance → evidence

| Acceptance item | Where it is proven |
|---|---|
| Import a multi-chapter fixture with a table, image/caption, code block, citation and math; edit; save; restart; round-trip; verify preservation | `tests/test_acceptance_phase02.py` (API, with a real restart of the app context), and Playwright `manuscript.spec.ts` (UI import → edit in CodeMirror → **hard-kill Core** → reload → recovered draft + saved revision → exports) |
| Restore a previous revision; the newer revision remains in history | same two tests, plus `test_manuscript.py::test_restore_creates_new_revision_and_keeps_history` |
| Reorder chapters; content/asset/citation references stay stable | `test_manuscript.py::test_reorder_does_not_orphan_references`, the acceptance test (re-parent + reorder + HTML export resolves image and citation), Playwright (buttons **and** drag-and-drop) |
| Backup → restore gives an equivalent manuscript and metadata | `test_backup.py::test_backup_then_restore_is_equivalent_and_never_overwrites` (compares every chapter, revision, label, note, draft, tree position, asset and metadata field), Playwright (UI backup download → Library restore) |
| Canonical schema round-trips without silent loss | `test_document_engine.py`: kitchen-sink fixture, plus a **150-example hypothesis property test** of serialize→parse identity. It found and fixed two real bugs: braces/quotes in attribute values, and tight-list item joining |
| Unsafe links, script injection, zip bombs, path traversal, size limits, encrypted/unreadable files | `test_imports.py` (scanned/encrypted PDF, legacy .doc, zip bomb, traversal, XXE, injection HTML, 413 over the limit, SVG refused), `test_backup.py` (tampered checksum, unlisted file, missing manifest, newer schema, unsafe archive paths, not-a-zip), Playwright "hostile and unreadable files" |
| Originals preserved, import reports, duplicates | `test_imports.py` (byte-identical download, DB immutability triggers, `previously_imported_at`, same-text and same-title duplicate detection) |

## Phase 02: what was built

**Core**
- `document/bookmd.py`: bookmd-1 → `bdm/1` (headings with anchors, paragraphs, tight/loose and task lists, quotes, GFM tables with alignment and captions, fenced code with language and attributes, inline and display math with labels, footnotes, citations with locators and author suppression, figures with alt ≠ caption, fenced divs, unsupported blocks kept verbatim). Fidelity warnings: missing alt, web/unresolved images, missing footnotes, duplicate anchors, unsafe links.
- `document/serialize.py` (normal-form writer, used by imports) and `document/html.py` (renderer + nh3 sanitizer, MathML via latex2mathml, inert unsafe links, no external image loads).
- Migration `0003`: originals, imports, assets, drafts, revision tags, project description, export formats, original-file immutability triggers.
- Services: chapter tree (part/chapter/section, max depth 3) and move/reorder; slug, title, status, kind and target edits; subtree archive; autosave drafts with conflict detection; revision list/get/compare (side-by-side, word-level)/restore-as-new/tag; preview; assets (content-addressed raster images); exports (Markdown or Markdown+images ZIP; standalone HTML with embedded images and a CSP); imports (md, txt, html, docx via mammoth, text PDF via pypdf); backup ZIP (manifest/1) and restore-as-new-project with ID remapping.
- `security/archive.py` (zip inspection, capped reads, DTD/XXE rejection); chunked upload limits (413).
- `fixtures/generate.py` and checked-in synthetic fixtures.

**UI**
- Book page: manuscript tree with drag-and-drop **and** Up/Down/Indent/Outdent buttons, chapter details (title, slug, status, target), nesting with progress bars, Markdown/HTML export, backups, and Import chapters.
- Editor: CodeMirror 6 source editor (Tab not captured) with a plain-textarea mode; Write / Write and preview / Preview views; Core-rendered preview with formatting notes; autosave drafts with recovery and stale-draft banners; Save/Ctrl+S; conflict dialog; a leave guard that offers "keep as draft" or "save revision"; Insert image (alt text required); History dialog (labels and notes, side-by-side diff using `<del>`/`<ins>`, restore as new); chapter quick-nav with previous/next.
- Import page (file input + drop zone, target book, preview with warnings, lossy notice, duplicates, per-chapter include, commit or cancel) and Library "Restore a backup".
- Navigation: **Import** added. Help text updated.

**Docs:** ADR-0002 (editor), ADR-0003 (export-engine spikes), plus as-built notes in DATA_MODEL, ARCHITECTURE, SECURITY, TEST_PLAN, ROADMAP and README.

## Decisions taken in Phase 02 (need your validation)

| # | Decision | Why | Reversible? |
|---|---|---|---|
| P2-1 | Source editor (CodeMirror) + Core preview instead of WYSIWYG (ADR-0002) | Lossless by construction; one renderer | Yes. A WYSIWYG must pass the fidelity suite first |
| P2-2 | Autosave writes a **draft** (mutable working copy). Only Save/restore/import create revisions | Keeps history meaningful (not one revision per keystroke) while never losing typing | Yes |
| P2-3 | Images referenced by **content hash** (`asset:<16 hex>`) | Duplicate, backup and restore need no text rewriting | Costly to change later |
| P2-4 | Originals stored workspace-wide (not per project), content-addressed, read-only | An upload exists before its project; dedupe | Yes |
| P2-5 | Restore always creates a new project titled "… (restored)", set to active | "No silent overwrite" | Yes |
| P2-6 | PDF import is text only and always marked lossy; scanned PDFs are refused (no OCR) | Honest about limits | Yes, later |
| P2-7 | Recommend **Typst** as the Phase 07 print-PDF engine (ADR-0003, D7) | WeasyPrint failed without GTK on Windows; the Typst wheel works offline | Decide in Phase 07 |

Still open from earlier: D6 (install Pandoc), D12 (public repo), D14 (prompt pack location), LICENSE choice.

## Known limitations (Phase 02, honest list)

1. **No WYSIWYG.** Writers edit Markdown with a live preview (ADR-0002).
2. **Word equations are not imported** (mammoth cannot convert OMML). They are detected and reported. Pandoc-based import would fix this (D6).
3. **PDF import recovers text only.** Headings are guessed from "Chapter …" lines; tables, images and footnotes are lost (reported). No OCR.
4. **HTML/DOCX import limits:** merged table cells are split (reported); sub/superscript and definition lists become plain text (reported); display math inside a paragraph becomes inline math.
5. **Citations are kept as keys.** Rendering is `(key, locator)`; bibliography formatting and key resolution arrive in Phase 04.
6. **No standalone annotation table** (comments on blocks). Revision labels and notes cover "revision labels and notes"; block annotations are deferred.
7. **Autosave conflict handling is last-writer-wins between two open tabs on the same base revision.** A later Save in either tab is still protected by the 409 check.
8. Drag-and-drop reorders among siblings and adopts the target's parent; nesting is done with Indent/Outdent. A drop "into" a chapter is not offered.
9. The footnote back-link renders on its own line in the preview (cosmetic).
10. macOS has not been run. Linux has not been run.
11. EPUB, DOCX and print PDF exports are Phase 07.
12. The stray `.pbs-test-run.log` from Phase 01 may still be at the repo root (git-ignored).

## Phase 03 handoff

Preserve: the `/api` contracts (regenerate TS with `scripts/gen-api`); the revision triggers (the AI-origin rule already requires `accepted_proposal_id`, which Phase 03's `proposal` table must satisfy); drafts are **not** revisions; `bookmd`/`bdm/1` invariants and the property test; `security/archive.py` and the upload caps; the import determinism check at commit.

Start Phase 03 with: the `proposal` and `job` tables (migration 0004); the egress gate before any HTTP client (keep the import-linter contract, adding an exception only for `pbs_core.providers`); the mock provider first; and AI output written as a proposal diffed against the head revision, using the same side-by-side diff component as History.

---

## Phase 01 evidence (real results, 2026-11-22, Windows 11, CPython 3.12.13, Node 26.13, pnpm 10.33)

Command: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1` → **exit 0, "All checks passed."**

| Check | Result |
|---|---|
| ruff lint / format (Core) | All checks passed / 54 files already formatted |
| mypy `--strict` (37 source files) | Success: no issues found |
| import-linter (3 contracts: pure domain/document, no network clients, layering) | 3 kept, 0 broken |
| pytest (Core) | **97 passed, 12 xfailed** (xfails = E2E-GOLDEN-01 steps owned by later phases, strict) |
| License gate (`scripts/check_licenses.py`) | passed: 53 runtime dependencies checked, no AGPL/GPL/SSPL/unknown |
| ESLint (incl. jsx-a11y strict, no `dangerouslySetInnerHTML`) + Prettier | clean |
| TypeScript (`tsc`, strict, app + node configs) | clean |
| Vitest + React Testing Library + axe-core | **11 passed** (3 files) |
| Vite production build | built |
| Playwright (Chromium 159) + @axe-core/playwright | **5 passed** |

Note: the first full run printed 96 pytest passes. `test_golden_path.py` was added afterwards and run separately: 1 passed, 12 xfailed. The full count above includes it.

### What the tests prove (mapped to the Phase 01 gates in ROADMAP.md)

| Gate | Evidence |
|---|---|
| G1.1 documented start commands | `scripts/dev.ps1` started Core + UI and the app was used in the browser (create book, add chapter, type, Ctrl+S → "Saved as revision 1", library card). The README lists the exact commands |
| G1.2 guard | `test_security.py`: no token → 401, wrong token → 401, bad Host / DNS-rebinding Host → 400, foreign Origin → 403 even with a token, `Sec-Fetch-Site: cross-site` → 403, no CORS headers ever, non-loopback `PBS_HOST` refused. `test_process_restart.py`: a real process listens on loopback only (netstat) |
| G1.3 migrations + immutability | `test_migrations.py`: fresh → head; head → head is a no-op; 0001 → 0002 with data preserved and a pre-migration snapshot; a newer DB is refused; models ≡ migrations (no drift). `test_chapters.py`: UPDATE/DELETE of revisions, AI-origin revision without a proposal, and non-sequential revision numbers are all rejected **by SQLite triggers**; composite FKs reject cross-project references |
| G1.4 CRUD + search/sort | `test_projects.py`: create/read/rename/edit, validation (no input echo), search over title/subtitle/audience/author with Unicode case-folding and LIKE escaping, filter by type/language/format, sort by title/type/language/audience/target/updated with nulls last, archive (read-only) and unarchive, duplicate (heads copied as revision 1, history not copied, original untouched) |
| G1.5 vertical slice | Playwright `vertical slice`: create book → add chapter → type a table, a tab/trailing-space code block, math and a citation → Save → **hard-kill Core and restart it** → reload → identical text → Export Markdown → downloaded file contains the chapter byte-for-byte. Also `test_process_restart.py` (real process kill/restart via API) |
| Isolation | `test_chapters.py::test_project_isolation_through_api` (404 for cross-project IDs, exports contain only their own project), DB-level composite FK test, Playwright `project isolation` |
| G1.6 navigation | Library, New book, Manuscripts, Activity and Help work. Research, Knowledge, Publishing and AI settings are `aria-disabled` and labeled "Not yet implemented (Phase NN)"; their URLs show an explicit not-implemented page (Vitest + Playwright) |
| G1.7 privacy badge | "Local-only" in the top bar, served from `/api/system/info` |
| G1.8 accessibility | axe: no serious/critical violations on library, new book, project and editor pages (Playwright, WCAG 2.2 AA tags). A real contrast failure on the privacy badge was found and fixed. A keyboard-only flow passes |
| Logging/redaction | `test_logs_never_contain_secrets`: canary keys in fields, messages and tracebacks never reach `logs/core.jsonl` |
| No external network | Session-wide pytest socket guard (non-loopback connect → error + test-suite failure). Import contract forbids network client libraries in `pbs_core`. The UI bundles fonts (no CDN) |

## What was built in Phase 01

**Backend (`apps/studio-core`, package `pbs_core`)**
- `config.py`: `PBS_*` settings. Host is forced to loopback; workspace resolution (dev `./.pbs-data`, prod `Documents/Personal Book Studio`).
- `storage/`: workspace layout, `safe_join` (absolute/drive/UNC/`..`/ADS/reserved names/trailing dots/symlink escapes), `sanitize_filename`, `slugify`, atomic writes; SQLite engine policy (WAL, `synchronous=FULL`, `BEGIN IMMEDIATE`, `pbs_fold`); models; programmatic Alembic migration with quick_check + online-backup snapshot + newer-DB refusal; `backup_manifest.py` (manifest/1 schema with safe archive paths).
- `migrations/`: `0001_baseline` (tables + 4 integrity triggers) and `0002_backup_run`.
- `security/`: per-launch 256-bit session token in `runtime/session.token` (runtime dir ACL restricted to the current user's SID via `icacls` on Windows, 0700/0600 on POSIX); ASGI guard; redaction processor.
- `logging_setup.py`: structlog JSON with redaction applied last, also for uvicorn and stdlib logs.
- `document/bookmd_v0.py`: lossless provisional parser (`bdm/0`), with block-ID reuse for unchanged blocks.
- `domain/`: ULIDs (monotonic), fractional position keys (property-tested), word count, typed domain errors.
- `services/`: projects, chapters (optimistic concurrency, approved-chapter lock, no-op on identical save), Markdown export (`pbs-md-export/1`), activity, capability detection (PATH lookup only).
- `api/`: problem+json errors (never echo input), routes per BUILD_STATE plan, app factory; `python -m pbs_core`; `pbs_core.openapi_export`; `pbs_core.tools.seed_demo` (explicit, labeled demo data).

**Frontend (`apps/studio-ui`)**: an original "bindery" design. Cool endpaper surfaces, blue-black ink, bookcloth spine colors per kind of book, a gilt ribbon whose length is real progress toward the target word count. Literata for manuscript and headings, Atkinson Hyperlegible for UI. Light and dark themes, reduced motion, responsive (drawer nav below 52rem). Pages: Library (search, filters, sort, active/archived/all, recent activity), New book, Project (details, edit dialog, duplicate, archive/unarchive, chapters with add/rename/archive, Markdown export with download and warnings, per-book history), Chapter editor (Markdown textarea, status, Save + Ctrl/Cmd+S, unsaved-changes guard for in-app navigation and tab close, 409 conflict dialog, approved-chapter lock with "Reopen for editing"), Manuscripts, Activity, Help (privacy explanation, workspace path, detected optional tools), not-implemented pages. Route-level error boundary, live-region toasts, skip link.

**Tooling**: `scripts/setup|dev|test|gen-api` (`.ps1` + `.sh`), `scripts/check_licenses.py`, Playwright fixtures that spawn and hard-kill a real Core, README with Windows/macOS commands and troubleshooting.

## Decisions taken in Phase 01 (defaults applied; the user had not answered D1–D14)

| # | Decision applied | Reversible? |
|---|---|---|
| D1 | CPython 3.12 (uv) | Yes (ADR) |
| D2 | Dev workspace `./.pbs-data` (git-ignored); prod default `Documents/Personal Book Studio` | Yes, via `PBS_WORKSPACE` |
| D3 | Core 127.0.0.1:8765, UI 127.0.0.1:5173 (both overridable) | Yes |
| D5 | Single `studio.db` with composite-FK isolation | Costly after Phase 02 |
| new | TypeScript 6.0 + ESLint 9 instead of TS 7 / ESLint 10 (plugin compatibility; ADR-0001 §7a) | Yes |
| new | Library search = case-folded substring, not FTS5 (DATA_MODEL §2.1) | Yes |
| new | `synchronous=FULL` always, rather than per-commit switching | Yes |
| new | API contract lives in `apps/studio-ui/src/api/` rather than `packages/contracts` | Yes |

Still open for the user: **D12** (the repo is public), **D14** (move the prompt pack to `docs/BUILD_PROMPTS.md`), a **LICENSE** choice (none added; currently "all rights reserved" by default), and D6–D11 for later phases.

## Known limitations (honest list)

1. **Editor is a plain Markdown textarea.** There is no preview, no autosave (manual Save / Ctrl+S only) and no formatting toolbar. The editor choice is ADR-0002 in Phase 02.
2. **Revision history has an API but no UI** (`GET …/revisions`). Diff and restore UI arrive in Phase 02.
3. **bookmd-0.1 models only top-level blocks.** Tables, math, footnotes, citations and attributes are preserved verbatim in the source and in block `src`, but they are not structured yet (`bdm/0`).
4. **No chapter reordering yet.** Positions are fractional keys ready for it (Phase 02).
5. **Backup:** only the data structure exists (manifest/1 schema, `backup_run` table) plus automatic pre-migration DB snapshots. The ZIP backup/restore flow is Phase 02.
6. **No imports** (Markdown/DOCX/HTML/PDF): Phase 02.
7. **Archive is the only removal action.** There is no permanent purge yet (by design; the `_purge_ctx` hook exists).
8. **macOS not verified.** `dev.sh`, `setup.sh` and `test.sh` have not been run. Keychain and ACL behavior on macOS are untested.
9. **The UI is dev-server only.** Core does not serve the built UI. A packaged runtime is Phase 10.
10. gitleaks is not installed locally, and there is no CI yet. The secret scan relies on `.gitignore` plus redaction tests.
11. The Vitest axe runs exclude `color-contrast` (jsdom cannot compute colors). Contrast is enforced in Playwright.
12. The Starlette TestClient's httpx deprecation warning is filtered in tests. Revisit when Starlette removes it.
13. The `preview_start` launcher (`.claude/launch.json`) did not start the script in the desktop app's browser pane. Running `scripts/dev.ps1` directly works.
14. A stray local log file `.pbs-test-run.log` may exist at the repo root from the evidence run. It is git-ignored (`*.log`) and safe to delete.

## Phase 02 handoff

Contracts to preserve: the `/api` routes and Pydantic contracts in `contracts.py` (extend, don't break; regenerate with `scripts/gen-api`); the revision immutability triggers; composite FKs; `expected_head_no` optimistic concurrency; the `pbs-md-export/1` format; the guard (token/Host/Origin); and the `safe_join`/`sanitize_filename` usage for every path.

Start Phase 02 with:
1. **bookmd-1 / `bdm/1`** per DATA_MODEL §4 (tables, math, footnotes, citations, attributes, figures with alt ≠ caption, divs). Add upcast from `bdm/0` by re-parsing `source_md`, plus the hypothesis round-trip suite and the `kitchen-sink.md` fixture.
2. **ADR-0002 editor bake-off** (CodeMirror 6 source mode as the leading candidate) and a server-rendered preview using one renderer shared with export.
3. **Revision UI**: list, diff (word-level), restore as a new revision with `origin=restored`, labels and notes, plus autosave with the existing 409 protection.
4. **Chapter reorder** (keyboard-accessible) using `key_between`.
5. **Imports** with preview, immutable `original_file`, import reports, and the malicious fixtures (zip bomb, XXE, traversal, XSS, encrypted/scanned PDF).
6. **Backup ZIP / restore-as-new** using `BackupManifest` (manifest/1) and `backup_run`.
7. **Spikes → ADR-0003**: WeasyPrint on Windows (Pango) vs Typst vs Chromium; ziamath/latex2mathml math; Pandoc DOCX via the BDM → Pandoc AST writer. (Pandoc, Java and GTK are still not installed on this machine.)

---

## Phase log

### Phase 05: Project planning (2026-11-22)
- Built as described in "Phase 05: what was built" on `phase/05-planning`.
- Open Library's search API was checked against its official docs before the adapter was written.
- Checked by hand in the desktop browser pane (Plan → Outline → the hand-written outline editor with a nested section and its tools), and end to end with Playwright against the built-in test model.

### Phase 04: Knowledge and evidence (2026-11-22)
- Built as described in "Phase 04: what was built" on `phase/04-knowledge`.
- Checked by hand in the desktop browser pane (book Sources page → search with highlights, locator and reasons), and end to end with Playwright against the built-in test model.

### Phase 03: AI providers and durable jobs (2026-11-22)
- Built as described in "Phase 03: what was built" on `phase/03-ai-jobs`.
- Provider endpoints were verified against the official docs by a research pass before the adapters were written.
- Checked by hand in the desktop browser pane (AI settings → built-in test model → AI assist → suggestion card), and end to end with Playwright against a loopback Ollama stub, including a hard Core crash mid-job.

### Phase 02: Editor, document model, history, imports, backup (2026-11-22)
- Built as described in "Phase 02: what was built" on `phase/02-editor-import-backup` (a WIP checkpoint commit, then a final commit).
- Verified in the real browser by hand (imported fixture → tree → editor split view with rendered math, citation, figure caption and footnotes) and with Playwright.
- Bugs found and fixed during the phase:
  - the property test found two serializer bugs (attribute values containing braces or quotes; tight lists with nested blocks);
  - the dollarmath plugin's first-character digit check (replaced by a currency guard);
  - inline-image alt text was lost;
  - explicit alt text set by the attrs plugin was ignored;
  - nested-transaction deadlock when an import created a project (moved project creation into the same transaction);
  - empty `<ins>` elements in the diff view;
  - axe: the scrollable diff region was not keyboard-focusable;
  - read-only originals blocked the e2e workspace wipe.
- Spikes recorded in ADR-0003.

### Phase 01: Scaffold and vertical slice (2026-11-22)
- Built backend, frontend, scripts and tests as described above, on branch `phase/01-scaffold`.
- Verified in a real browser (in-app pane): create book → add chapter → type → Ctrl+S → library card shows 10 words and 1 chapter.
- Fixed during the phase: menu-toggle CSS specificity, the library filter row overflowing at 1024px, a privacy-badge contrast failure (axe), openapi-fetch capturing `fetch` at import time (broke test mocking), and Windows console encoding in the license gate and OpenAPI export.

### Phase 00: Planning (2026-11-22)
- Inspected the repo and environment. Created PRD, ARCHITECTURE, DATA_MODEL, SECURITY, ADR-0001, TEST_PLAN, ROADMAP and BUILD_STATE plus `.gitignore` and `.gitattributes`. Committed and pushed to `main`.

## Environment snapshot (2026-11-22)

Windows 11 Pro for Workstations x64. git 2.50.1, gh 2.96.0. Python default 3.15.2 (**not used**), 3.13.1, 3.12.13 (uv). uv 0.11.15 (needs `UV_LINK_MODE=copy`). Node 26.13.0, pnpm 10.33.0. Rust 1.95.0 (MSVC host), VS BuildTools present, WebView2 157. Docker 29.9.2. Playwright 1.65 / Chromium 1255 cached.
**Missing (not needed until later phases):** Pandoc, Java/EPUBCheck, Ollama, GTK/Pango (WeasyPrint), Tesseract, Calibre, Typst CLI.
