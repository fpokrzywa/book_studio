# ADR-0006: Planning: brief, research, outline, skeleton and generation runs

Status: Accepted (Phase 05, 2026-11-22).

## Context
Phase 05 takes a book from an idea to an approved outline and lets the author draft chapters from it. The constraints:
- market metrics are never fabricated;
- research providers are used only when configured, and fail explicitly;
- an outline proposal must be approved before any bulk drafting;
- an outline change never destroys prose or history;
- manual edits and locks are honoured in every mode;
- cost and time are previewed as estimates, under a hard budget cap and a chapter limit.

## Decisions

### 1. Wizard and brief
**Wizard.** The New Book wizard is the existing project form (title, kind, language, audience, target length, formats) plus three optional steps:
- reader and promise;
- shape and sources;
- approvals and budget.

It posts once to `POST /api/books`, which creates the project and its brief and links the chosen shared libraries.

**Brief kind.** The kind comes from the project type: fiction and serial map to fiction; course and technical map to manual.

**Brief contents:**
- target reader, core promise, purpose, value proposition, exclusions;
- the teaching arc (nonfiction) or plot arc (fiction);
- explicit factual and creative assumptions;
- the approval preference, budget cap and currency, chapter limit per run, and the author's words-per-hour (used only to estimate writing hours).

**Approval and versioning.** Approving a brief records its version. Any change to an approved brief makes it a draft again, with the version number increased.

### 2. Research: evidence vs heuristics, and no market figures
**Findings** have a `kind` (measured, heuristic, note, competitor, keyword, topic, query) and an `origin` (author, ai_brainstorm, provider). The UI and the API's `evidence` field split them into exactly two groups:
- **measured**: needs a named source; enforced by a DB CHECK and by the API;
- **heuristic**: everything else.

**No market figures without a licensed source.** PBS has no licensed source for sales rank, market size, demand, competition scores, bestseller status or search volumes, so:
- **AI brainstorms** (topics, queries, KDP keyword ideas) go through `strip_metric_claims`. Any sentence stating such a figure is removed, and the finding is flagged; an item that was nothing but a claim is dropped. Keyword ideas carry `no_search_volume_data`.
- **AI findings can never become measured**, and only provider rows may hold `metrics_json`. Both rules are DB CHECKs. No provider supplies metrics today.
- **Text the author types** is kept as written. A market figure without a source is flagged `unsourced_metric` and shown as an opinion.
- **Prompts** tell the model it has no market data and must not state any.

**Provider search.** The only real adapter is the Open Library search API (verified 2026-11-22):
- only bibliographic fields are requested and kept (title, authors, first year, publisher, edition count, subjects);
- Open Library's reading-log counts and ratings are deliberately not requested;
- requests use a generic User-Agent with no personal details;
- search is off by default and needs privacy mode `cloud_allowed`;
- traffic goes through the egress gate (allowlist `openlibrary.org`);
- only the words the author types are sent, never the manuscript.

A deterministic test catalogue exists in development and test only.

**Fail-safe.** A provider that is off, blocked (local-only mode) or failing returns 409 `research_unavailable` with:
- `reason` set to `not_configured`, `blocked` or `failed`;
- a sentence saying nothing was searched or added.

Every attempt is logged in `research_query`, including the provider's raw results. "Save as comparable title" copies from that server-side record; the client cannot inject data.

### 3. Outline versions
- **Immutable versions.** Each outline version is a snapshot (`draft`, `proposed`, `approved`, `superseded`, `rejected`). At most one version per book is approved (partial unique index).
- **The author edits one working draft.** "Edit it first" or "Edit as a new draft" copies any version into that draft.
- **AI output is always a new `proposed` version.** It never overwrites the draft or the approved outline. The author's locked entries are carried into the proposal unchanged, and the model is told not to duplicate them.
- **Node IDs** (`n_<ULID>`) are stable across edits and versions.
  - Merge keeps the first node's ID.
  - Split gives the second half a new ID.
  - Structure is validated on the server: part > chapter > section, at most 500 nodes.
- **Per-chapter requirements.**
  - Nonfiction: `citations_min`, source IDs and notes.
  - Fiction: plot points, characters and continuity.
- **Estimates.** Totals show target words and estimated writing hours, labelled as estimates.

### 4. Applying an approved outline (skeleton)
`planning/skeleton.apply` maps nodes to chapters by `chapter.outline_node_id`. For each case:

| Case | What happens |
|---|---|
| Matched chapter | Its title, kind, place and target follow the node |
| Matched chapter that is **locked or approved** | Left exactly as it is, and reported |
| New node | Becomes an empty `planned` chapter |
| Node removed, chapter empty | Chapter is **archived** (reversible: it is restored if the node returns) |
| Node removed, chapter has prose, a draft or live children | Chapter is **kept**, and reported |
| Chapter added by hand (no node) | Kept, and reported |

**Sections** stay inside their chapter as `##` headings when the chapter is drafted; they do not become chapter rows. This keeps one document per chapter.

**Prose is never touched.** No revision or draft is read for content, changed or deleted.

### 5. Generation modes, locks, limits and budget
**Modes:**
- **outline first**: an outline proposal;
- **one chapter**: one chapter from the applied, approved outline. It may continue a chapter that has text, as an appended suggestion;
- **entire book**: every eligible chapter.

**Eligibility.** Locked and approved chapters and chapters with unsaved changes are always skipped. In entire-book mode, chapters that already have text are skipped as well. Every skip is reported with its reason.

**Every job is a normal chapter proposal.** Nothing is applied without review, whatever the approval preference. The instruction is built from the brief and the node: goal, sections as `##` headings, requirements, exclusions and tone. After generation, a requirement check is stored with the proposal: citations found against citations required, and characters named. Plot points and continuity are marked "review yourself".

**Estimate before starting:**
- input and output tokens per chapter;
- a cost upper bound from the author's prices ("unknown" when no price is entered);
- a time estimate only from this workspace's **measured** throughput for that model; otherwise it says "unknown".

**Hard limits.** A run is refused when:
- it would exceed the chapter limit;
- the cost cannot be estimated while a cap is set;
- the currencies differ;
- the upper bound is above the cap.

**While running**, each finished chapter adds its actual cost. Reaching the cap, or a cost that cannot be determined while a cap is set, cancels the remaining queued chapters and stops the run with the reason. Local models cost nothing and are never capped.

### 6. Backup
The brief, research findings and every outline version are part of a book backup. Node IDs are kept, so restored chapters stay linked to the approved outline and can be drafted at once. Research query logs and run records are not backed up.

## Consequences and limits
- No licensed market data source exists. Market questions are answered with "not available", by design.
- The time estimate needs history. The first run on a model always shows "time unknown".
- Plot and continuity requirements are not machine-checked.
- Outline generation is a single model call. Very long books depend on the model's output limit, and the author can raise `max_output_tokens`.
