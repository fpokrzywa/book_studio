# ADR-0007: Writing pipeline, editor actions, quality reviews and originality

Status: Accepted (Phase 06, 2026-11-22).

## Context
Phase 06 turns an approved outline into chapter drafts. The constraints:
- drafts are written section by section, not in one giant prompt;
- each prompt gets the brief, the local outline, earlier-chapter summaries, the style guide, source passages, continuity notes, targets and exclusions, all within an explicit token budget;
- failed sections are retried alone, and drafts can be paused, resumed, cancelled and reviewed;
- AI writes only into proposed revisions and never overwrites accepted or locked text;
- editor actions show a diff and must not change code or equations;
- quality reviews mark problems without claiming factual correctness;
- an originality report states its scope.

## Decisions

### 1. A draft plan per chapter, one job per section
`draft_plan` (one chapter) and `draft_section` (one outline section). Each section is a normal durable job (Phase 03 runner: lease, retry, cancel, restart recovery) with input `kind = "section_draft"`.
- **Section output lives on the plan**, never in the chapter.
- When every section is done, the plan **assembles one proposal**: the sections joined under `## Section title` headings, appended to the chapter.
- The chapter changes only when the author accepts that proposal, which goes through the existing accept path (unique index, expected head, unsaved-draft check).
- **Generation runs** (Phase 05 "Draft chapters") now create one plan per eligible chapter. The chapters of a run are drafted in order: a plan starts when the previous chapter is assembled, so it can use that chapter's summary.
- A chapter outline node without sections becomes a single section with the chapter's goal and no extra heading.

### 2. Context and the token budget
The prompt for a section is assembled **when the job runs** (like Phase 04 retrieval). `writing/context.fit` takes the parts in priority order:

| Part | Kind | Rule |
|---|---|---|
| Book brief | required | always sent |
| Local outline, targets and exclusions | required | always sent; the current section is marked |
| This chapter so far | text | trimmed from the start (the end is kept) |
| Approved style guide | text | trimmed |
| Continuity memory | items | confirmed notes first, then proposed ones |
| Earlier chapters (summaries) | items | nearest chapter first |
| Knowledge passages and interview answers | items | in retrieval order; only kept passages can be cited |

- Required parts are trimmed proportionally only if they alone exceed the budget.
- The budget (default 6,000 input tokens; minimum 1,500) is an **estimate** at about four characters per token. 450 tokens are reserved for the fixed instructions.
- The per-part report (tokens and included/trimmed/dropped/empty) is stored with the section and shown in the UI and the job log.

### 3. Chapter summaries and running continuity memory
- Each section reply is structured JSON: `{text, summary, facts}`. The summaries become a `chapter_summary` row when the chapter is assembled.
- **Facts** (characters, places, relationships, events with story time, open threads; key terms in nonfiction) become `continuity_fact` rows with status `proposed`. The author confirms, rejects or resolves them, and can add their own (confirmed).
- **Rejected inputs are never sent:** rejected facts, and the summaries and facts of a draft whose proposal was rejected.
- A chapter with text but no summary contributes its first lines, labelled as such.

### 4. Pause, cancel, resume, retry, review gates
- **Pause** stops after the running section. A queued section is cancelled and returns to pending.
- **Resume** re-queues a failed or cancelled section, or else continues with the next pending section.
- **Cancel** keeps finished sections and creates no proposal.
- **Retry** works on one failed or cancelled section. A finished section is never sent again (409).
- **Review gate** `each_section` stops the plan after every section. The author may edit the text (marked `edited`) and approves it to continue.
- Stopping a run (author, budget cap, unknown cost) cancels its plans.

### 5. Locked and approved chapters
Chapters gain an author-controlled `locked` flag ("Lock against AI changes").
- Locked or approved chapters are never planned, and editor/AI requests on them are refused.
- A suggestion for a chapter that became locked or approved **cannot be applied** until the author unlocks or reopens it.
- Accepted revisions are immutable (Phase 01 triggers), and nothing in the pipeline writes revisions.

### 6. Editor actions, protected content and diffs
**Actions.** `action` on an AI request maps to a task, a placement and an instruction:
- rewrite, expand, shorten, tone (needs the author's wording), clarity, repetition, transitions: replace the selection;
- explain: a note;
- exercises, quiz, glossary: inserted after the selection.

**Protected content.** Before a revise or translate request is sent, fenced code blocks, inline code and math in the selection are replaced by numbered placeholders.
- Every placeholder must come back exactly once, and the originals are restored byte for byte.
- A reply that drops, repeats or invents a placeholder is `invalid_output`: it is retried, and if it keeps happening it fails without a proposal.

**Diff.** Replacement proposals carry a word-level diff (`domain/diff.inline`). The review card shows it with `<del>`/`<ins>`.

### 7. Quality reviews
`writing/quality.py` holds deterministic local checks with stable fingerprints. The author's decision survives re-runs: `open`, `needs_source`, `will_fix`, `dismissed` or `fixed`. Findings that disappear are kept and marked "no longer found".

| Check | What it finds |
|---|---|
| style | doubled words; sentences over 45 words. Hints only, not a grammar checker |
| repeated_phrase | a 5-word phrase (at least 3 content words) used 3 or more times in a chapter |
| duplicate_paragraph | identical paragraphs, or paragraphs ≥ 80% the same, across the book (12+ words) |
| unsupported_claim (nonfiction) | factual-looking sentences (percentages, dates, large numbers, "studies show", "according to", superlatives, quantity claims) in a paragraph with no citation |
| missing_citations (nonfiction) | fewer `[@…]` citations than the outline's `citations_min` |
| outline_mismatch | outline sections without a heading; length outside 50–150% of target; topics the brief excludes |
| broken_link | `#anchor` links to anchors that do not exist; malformed web addresses (form only: links are never visited); unsafe links and unresolved images |
| missing_alt | figures without alt text |
| inconsistent_term | hyphen and space variants (e-mail / email / e mail) |
| undefined_acronym | 2–6 capital letters never spelled out "Full Name (ABC)" (common ones and Roman numerals ignored) |
| continuity (fiction) | one character, place or term with different values; event years out of chapter order (possible flashback); open threads |
| code_syntax | Python and JSON blocks that do not parse. **Only when the author allows code checks for the book; code is parsed, never executed** |

**AI review** (`kind = "quality_review"`, task `revise` route) asks the model for findings with exact quotes.
- A finding is kept only if its quote is really in the chapter.
- Kept findings are labelled "AI review, not proof", with a disclaimer stored on each.

### 8. Originality report
Local only. It reports repeated paragraphs within the book, and runs of 12 or more identical words shared with the other books in this workspace or with this book's knowledge sources (with a "cited in paragraph" flag).
- It lists what is not covered: the web, published works, paraphrase and translation.
- It says that no external similarity provider is configured; PBS ships none.
- It always states that **finding no match is not proof of originality or of non-infringement**.

### 9. Backup
Continuity notes, chapter summaries and quality findings (with decisions) are part of a book backup. Finding fingerprints are recomputed for the restored chapter IDs, so decisions survive.

Draft plans, sections and their job history are working records and are not backed up, like runs and job logs.

## Consequences and limits
- Section-level JSON needs a model that follows JSON instructions; malformed replies are retried, then fail visibly.
- Token counts are estimates. A model with a smaller context window than the budget can still overflow.
- Summaries come from the model's own section summaries; they are not checked against the text.
- Continuity checks compare structured notes, not the prose itself. A trait changed only in prose is caught only by the AI review or the author.
- The fact-like-sentence rules are English-centric heuristics; they over- and under-flag.
- No code execution sandbox exists, so code is parsed only.
