# Feature matrix

Every requirement in `docs/PRD.md` (§4 functional, §5 non-functional, §6 governance) and every
function Prompt 11 names, with the evidence that proves it. Compiled 2026-11-23 in Phase 11.

**Statuses**

| Status | Meaning |
|---|---|
| **PASS** | An automated test exercises the real behaviour. |
| **PARTIAL** | Works, but part of the requirement is missing, limited or untested (see the note). |
| **NOT TESTED** | Implemented, with no test. |
| **NOT IMPLEMENTED** | No code. |
| **BLOCKED** | Needs something not available here: real cloud keys, tools that are not installed, or a permission that was not granted. |

A screen existing is never evidence on its own.

**Where the tests live:** `core` = `apps/studio-core/tests/`, `ui` = `apps/studio-ui/src/features/`,
`e2e` = `e2e/`, `deploy` = `deploy/validation/run_e2e.sh` (run on Ubuntu behind Nginx Proxy Manager).

**AI coverage.** Most AI tests use the built-in **test model** (deterministic, not AI). The Playwright AI
spec uses a loopback **Ollama stub**. Only the Ubuntu deployment validation used a **real local model**
(`qwen2.5:0.5b`).

## Summary

| Status | Rows (of 100, counted from the tables below) |
|---|---|
| PASS | 70 |
| PARTIAL | 26 (includes rows marked "PARTIAL / BLOCKED") |
| BLOCKED | 3 (EPUBCheck validation; narration and transcription with real engines, twice) |
| NOT IMPLEMENTED | 1 (EPUB import). Permanent book deletion and per-block origin badges are missing parts of PARTIAL rows |

Some rows overlap (the Prompt 11 lists repeat PRD items), so the counts describe rows, not distinct features.

## Prompt 11 core functions

| Function | Status | Evidence | Note |
|---|---|---|---|
| Project and book creation | PASS | core `test_projects.py`; e2e `vertical-slice.spec.ts`; deploy | |
| Markdown import | PASS | core `test_imports.py::test_markdown_import_is_lossless_and_split_by_headings`; core `test_final_acceptance.py` | Original kept byte for byte (asserted) |
| DOCX import | PASS | core `test_imports.py::test_docx_import`; deploy (DOCX with table, lists, image) | Word equations are not imported |
| PDF import | PASS | core `test_imports.py::test_text_pdf_import_is_marked_lossy` | Text PDFs only; scanned PDFs are refused with a warning (no OCR) |
| **EPUB import** | **NOT IMPLEMENTED** | — | Not in PRD FR-IMP-1; no EPUB importer exists. Recommended next improvement |
| Chapter extraction and structure | PASS | core `test_imports.py`, `test_document_engine.py`, `test_final_acceptance.py`; deploy | |
| Editor and version history | PASS | core `test_manuscript.py`, `test_chapters.py`; ui `ChapterEditorPage.test.tsx`; e2e `vertical-slice.spec.ts` | Side-by-side compare only (no separate inline diff view) |
| AI chapter generation and rewriting | PASS (test model) / PASS (real local model, deploy) | core `test_writing.py`, `test_ai_jobs.py`; deploy (revise with `qwen2.5:0.5b`) | Quality of AI writing not judged |
| AI editing with human approval | PASS | core `test_ai_jobs.py`, `test_final_acceptance.py` (reject leaves text; accept makes one revision; double accept refused); e2e `ai.spec.ts`; deploy | |
| Knowledge bases and citations | PASS | core `test_knowledge.py`; e2e `knowledge.spec.ts`; core `test_final_acceptance.py` (citation and bibliography in DOCX, EPUB, PDF) | Lexical search only (no semantic search) |
| Author personas and writing styles | PASS | core `test_voice_interview_backup.py`, `test_advanced.py::test_pen_name_voice_rules_shown_per_project_and_used_in_prompts` | Style analysis is English-centric |
| Market research and outlining | PARTIAL | core `test_planning.py`; e2e `planning.spec.ts` | No licensed market-data source; brainstorming is labelled heuristic. Open Library never called live |
| Book covers and layouts | PARTIAL | core `test_publishing.py` (covers, templates, trims) | No image-generation provider; RGB covers only; no hardcover |
| DOCX, EPUB, PDF exports | PASS | core `test_publishing.py`, `test_final_acceptance.py` (per-format inspection); e2e `publishing.spec.ts`; deploy | DOCX keeps equations as LaTeX text; PDF prints link addresses ("degraded", reported) |
| Print formatting and preflight | PASS | core `test_publishing.py` (page size, margins, fonts, images, page count) | Preflight is a helper, not a store's approval |
| EPUB validation with EPUBCheck | **BLOCKED** | core `test_epub_validation_is_unavailable_never_passed_without_epubcheck` | EPUBCheck is not installed. Downloading and running it was refused by this session's permission settings. The studio's own EPUB checks pass. Command to run it yourself: KNOWN_ISSUES |

## Prompt 11 Phase 08 functions

| Function | Status | Evidence | Note |
|---|---|---|---|
| Multi-book series | PASS | core `test_advanced.py`; e2e `advanced.spec.ts` | |
| Story bible and continuity | PASS | core `test_advanced.py::test_series_canon_contradiction_and_resolution_survive_rerun`; e2e | Narrow, English-centric rules |
| Character relationships | PASS | core `test_advanced.py::test_relationship_check_and_suggestions_are_not_canon`; ui `Series.test.tsx` | |
| Pen-name profiles | PASS | core `test_advanced.py::test_pen_name_voice_rules_shown_per_project_and_used_in_prompts` | |
| Translation and localised editions | PASS (test model) | core `test_advanced.py::test_translate_one_chapter_without_touching_source`; e2e | Original unchanged (asserted); translation quality not evaluated |
| Narration and transcription with providers | **BLOCKED** | core `test_advanced.py::test_cloud_speech_and_transcription_when_allowed` (recorded wire format) | No real engine installed; no real cloud key used |
| Graceful behaviour without providers | PASS | core `test_advanced.py::test_narration_degrades_gracefully_without_an_engine`, `::test_transcription_degrades_without_whisper`; e2e `advanced.spec.ts` | |
| Originals never altered | PASS | translation and narration tests assert source revision and text unchanged | |

## PRD §4 functional requirements

| ID | Status | Evidence | Note |
|---|---|---|---|
| FR-LIB-1 | PARTIAL | core `test_projects.py` (rename, archive, duplicate) | **Permanent deletion NOT IMPLEMENTED**; archive is the only removal |
| FR-LIB-2 | PASS | core `test_projects.py::test_create_and_read_back`; ui `ProjectForm.test.tsx` | |
| FR-LIB-3 | PASS | core `test_projects.py::test_search_filter_sort`; ui `LibraryPage.test.tsx` | |
| FR-LIB-4 | PARTIAL | ui `LibraryPage.test.tsx` | Demo seed script untested |
| FR-MS-1 | PASS | core `test_manuscript.py`, `test_chapters.py`; ui `ManuscriptTree.test.tsx` | |
| FR-MS-2 | PASS | core `test_document_engine.py` | Markdown source and preview, not WYSIWYG (ADR-0002) |
| FR-MS-3 | PASS | core `test_document_engine.py` (property test), `test_acceptance_phase02.py` | |
| FR-MS-4 | PASS | core `test_manuscript.py`, `test_chapters.py::test_stale_save_conflicts_without_writing` | Drafts: last writer wins between two open tabs (saves are protected) |
| FR-VER-1 | PASS | core `test_chapters.py`, `test_ai_jobs.py` | |
| FR-VER-2 | PARTIAL | core `test_manuscript.py::test_compare_side_by_side_with_word_highlights` | No separate inline diff view |
| FR-VER-3 | PASS | core `test_manuscript.py::test_restore_creates_new_revision_and_keeps_history` | |
| FR-VER-4 | PARTIAL | core `test_backup.py` | Per-book backups omit Phase 08 data. The whole-studio backup includes everything (deploy) |
| FR-IMP-1 | PASS | core `test_imports.py` | |
| FR-IMP-2 | PASS | core `test_imports.py::test_original_is_immutable_and_downloadable`, `test_final_acceptance.py`; deploy (SHA-256 of original) | |
| FR-IMP-3 | PASS | core `test_imports.py`; ui `ImportPage.test.tsx` | |
| FR-IMP-4 | PASS | core `test_imports.py` | |
| FR-IMP-5 | PASS | core `test_imports.py`, `test_backup.py`, `test_web.py`; e2e `manuscript.spec.ts` | |
| FR-AI-1 | PARTIAL / BLOCKED | core `test_ai_providers.py` (recorded wire formats); deploy (Ollama) | Cloud adapters never called with real keys |
| FR-AI-2 | PASS | core `test_ai_providers.py::test_local_only_mode_makes_zero_external_calls`, `test_ops.py::test_operator_cloud_switch_forces_local_only` | |
| FR-AI-3 | PASS | core `test_ai_jobs.py::test_task_route_is_used_and_estimate_is_labelled` | |
| FR-AI-4 | PARTIAL | core `test_ai_providers.py`, `test_web.py` | Server mode uses an AES-GCM encrypted file with a Docker-secret master key (P9-8), not an OS store |
| FR-AI-5 | PASS | core `test_ai_jobs.py`, `test_ai_providers.py`; ui `Ai.test.tsx` | Token counts are estimates (about 4 characters per token) |
| FR-AI-6 | PASS | core `test_process_restart.py`, `test_ai_jobs.py`; deploy (worker killed mid-job) | Bounded concurrency implemented but not asserted by a test |
| FR-AI-7 | PASS | core `test_ai_jobs.py`, `test_writing.py`, `test_final_acceptance.py` | |
| FR-KB-1 | PASS | core `test_knowledge.py` | |
| FR-KB-2 | PARTIAL | core `test_knowledge.py`; e2e `knowledge.spec.ts` | Semantic search unavailable |
| FR-KB-3 | PASS | core `test_knowledge.py` | Test model |
| FR-KB-4 | PASS | core `test_knowledge.py` | |
| FR-KB-5 | PARTIAL | core `test_knowledge.py` | Retrieval time and hash stored but not asserted |
| FR-KB-6 | PASS | core `test_voice_interview_backup.py` | |
| FR-KB-7 | PASS | core `test_voice_interview_backup.py` | |
| FR-PLN-1 | PASS | core `test_planning.py`; e2e `planning.spec.ts` | |
| FR-PLN-2 | PARTIAL | core `test_planning.py` | Open Library via mock transport only |
| FR-PLN-3 | PASS | core `test_planning.py` | |
| FR-PLN-4 | PASS | core `test_planning.py` | |
| FR-PLN-5 | PASS | core `test_planning.py` | |
| FR-WR-1 | PASS | core `test_writing.py` | Test model |
| FR-WR-2 | PARTIAL | core `test_writing.py`; e2e `writing.spec.ts` | 4 of 11 actions asserted |
| FR-WR-3 | PARTIAL | core `test_writing.py` | Grammar only via AI review; rules English-centric |
| FR-WR-4 | PARTIAL | core `test_writing.py`, `test_advanced.py` | Narrow rules; pronoun-only sentences not linked |
| FR-WR-5 | PASS | core `test_writing.py::test_originality_report_states_its_scope` | Local overlap only, as stated |
| FR-PUB-1 | PASS | core `test_publishing.py::test_front_matter_never_invents_legal_text_or_isbn` | |
| FR-PUB-2 | PASS | core `test_publishing.py` | |
| FR-PUB-3 | PASS | core `test_publishing.py`, `test_final_acceptance.py`; deploy | |
| FR-PUB-4 | PARTIAL | core `test_publishing.py` | No image provider; RGB only; no hardcover |
| FR-PUB-5 | PARTIAL / BLOCKED | core `test_publishing.py` | Honest "unavailable" tested; EPUBCheck itself blocked |
| FR-PUB-6 | PASS | core `test_publishing.py::test_publish_package_has_everything_and_publishes_nothing` | |
| FR-ADV-1 | PASS | core `test_advanced.py`; e2e `advanced.spec.ts` | |
| FR-ADV-2 | PASS | core `test_advanced.py` | |
| FR-ADV-3 | PASS | core `test_advanced.py` | |
| FR-ADV-4 | BLOCKED | core `test_advanced.py` (degrade paths PASS) | No real engines |
| FR-ADV-5 | PARTIAL | core `test_planning.py` | No licensed data source |
| FR-UX-1 | PARTIAL | e2e `ai.spec.ts` (revision origin in history) | **Per-block origin badges not implemented**; origin is per revision |
| FR-UX-2 | PARTIAL | ui `LibraryPage.test.tsx`; e2e | "Cloud call active" indicator untested (no real cloud call) |
| FR-UX-3 | PARTIAL | core `test_projects.py`, `test_security.py` | Activity feed not scanned for secrets |
| FR-UX-4 | PASS | ui `Ai.test.tsx`; e2e `ai.spec.ts`; core `test_writing.py` | |
| FR-UX-5 | PARTIAL | axe in 12 Vitest and Playwright files; e2e keyboard-only test | Automated only; no manual screen-reader audit; reduced motion untested |
| FR-UX-6 | PASS | ui `LibraryPage.test.tsx`; e2e `vertical-slice.spec.ts` | |

## PRD §5 non-functional and §6 governance

| ID | Status | Evidence | Note |
|---|---|---|---|
| NFR-1 Privacy | PASS | core `test_ai_providers.py`, `test_advanced.py`, conftest network guard; deploy (cloud switch) | |
| NFR-2 Durability | PASS | core `test_process_restart.py`, `test_paths.py`; deploy (restart, recreate, kill) | Pragmas not asserted directly |
| NFR-3 Integrity | PASS | core `test_chapters.py`, `test_imports.py`, `test_ai_jobs.py` | |
| NFR-4 Performance | PARTIAL | Phase 11 measurement (BUILD_STATE): library 85 ms, chapter tree 46 ms, full-text search 41 ms, EPUB 2.7 s for 100 chapters / 500 images / 10k chunks | API timings on the dev machine; editor keystroke latency not measured |
| NFR-5 Portability | PARTIAL / BLOCKED | Windows 11; Linux image; Ubuntu 24.04.5 in a container | macOS never run; no physical Ubuntu host |
| NFR-6 Recoverability | PASS | core `test_migrations.py`, `test_backup.py`, `test_ops.py`; deploy (backup, restore, isolated restore, rollback) | |
| NFR-7 Observability | PARTIAL | core `test_security.py`, `test_web.py`; deploy (no secrets in logs) | Rotation configured, not tested |
| NFR-8 Licensing | PASS | `scripts/check_licenses.py` gate (101 dependencies) | |
| Gov 1 User owns the work | PASS | imports, backup, archive tests | |
| Gov 2 AI proposals only | PASS | `test_ai_jobs.py`, `test_writing.py`, `test_planning.py`, `test_final_acceptance.py` | |
| Gov 3 Sources untrusted | PASS | `test_knowledge.py`, `test_imports.py` | Simulated hostile model only |
| Gov 4 Attribution | PASS | `test_knowledge.py` | |
| Gov 5 Local-only fails closed | PASS | `test_ai_providers.py`, `test_ops.py` | |
| Gov 6 Credentials | PARTIAL | `test_ai_providers.py`, `test_web.py`; deploy log scan | Encrypted file on servers; no gitleaks scan |
| Gov 7 Originality limits | PASS | `test_writing.py` | |
| Gov 8 AI-generated vs assisted | PARTIAL | `test_ai_jobs.py` | Per revision, not per block |
| Gov 9 No automatic publishing | PASS | `test_publishing.py` | |
| Gov 10 Nothing fabricated | PASS | `test_planning.py`, `test_knowledge.py`, `test_ai_jobs.py` | |
