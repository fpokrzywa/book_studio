# ADR-0004: AI provider integration, egress gate and durable jobs

Status: Accepted (Phase 03, 2026-11-22). Supersedes the provider sketch in ARCHITECTURE §7 where they differ.

## Context

Phase 03 adds AI: local (Ollama) and cloud (OpenAI, Anthropic, Google Gemini, Groq, xAI Grok) providers. The constraints that shaped every choice:
- local-only by default, failing closed;
- no silent local→cloud fallback;
- keys only in the OS credential store;
- AI output is always a proposal;
- no invented models, prices or capabilities;
- jobs survive restarts without double-applying.

## Decisions

### 1. One network path, gated per request
All provider HTTP goes through `providers/egress.gated_client()`. This is an **httpx2** client (the HTTP library the current `openai` and `anthropic` SDKs are built on) with these settings:
- a `request` event hook that re-checks every request;
- `follow_redirects=False`;
- `trust_env=False`, so no environment proxies are used.

The rules:
- **Loopback is always allowed.** Loopback means `127.0.0.0/8`, `::1` and `localhost`.
- **Everything else needs all of the following:**
  - privacy mode `cloud_allowed`;
  - for project work, a `cloud_consent` row for that project and provider;
  - a host on that provider's fixed allowlist;
  - https.

Violations raise `EgressBlockedError` before a connection opens. Adapters also check the base URL before calling an SDK.

Two counters feed the privacy badge and the AI settings page:
- `external_requests()`: requests that passed the gate to a non-loopback host;
- `active_cloud_calls()`: calls in progress.

In local-only mode `external_requests()` stays empty, and tests assert this.

import-linter enforces that `httpx`, `httpx2`, `requests`, `urllib3`, `aiohttp`, `openai` and `anthropic` are imported only inside `pbs_core.providers`.

### 2. Official SDKs where they exist, documented REST elsewhere
All endpoints were verified against the official docs on 2026-11-22. Facts that could not be confirmed are listed in each module's docstring.

| Provider | How | Notes from the docs |
|---|---|---|
| Anthropic | `anthropic` SDK (`messages.stream`, `models.list`) | Structured output through `output_config.format` (json_schema). Current API versions reject `temperature`, so it is never sent. `stop_reason == "refusal"` is reported, not retried. `models.list` reports context, max output and structured-output support |
| OpenAI | `openai` SDK, Chat Completions | Uses `max_completion_tokens`, not the deprecated `max_tokens`. `stream_options.include_usage` is sent. A 429 with `insufficient_quota` counts as billing and is not retried. `/v1/models` reports no capabilities |
| Groq | `openai` SDK at `https://api.groq.com/openai/v1` | Structured output cannot be combined with streaming, so structured requests are sent unstreamed. `include_usage` is unverified and not sent. The models list gives `context_window` |
| xAI (Grok) | `openai` SDK at `https://api.x.ai/v1` | Chat Completions is labelled "legacy" (Responses is recommended). The models list gives `context_length` |
| Gemini | REST `streamGenerateContent?alt=sse` | The key goes in the `x-goog-api-key` header, never in the URL. `generateContent` is "legacy but fully supported". The newer Interactions API is not used yet. `temperature` is sent only when the author sets one, because Gemini 3.6+/4 ignore it and may later reject it |
| Ollama | REST `/api/version`, `/api/tags`, `/api/show`, NDJSON `/api/chat` | Every NDJSON line is checked for `error`, since mid-stream errors arrive with HTTP 200. Context length comes from `model_info["<arch>.context_length"]`. Only loopback servers are accepted |

"Grok" (xAI) and "Groq" are different companies. Both are supported.

Chat Completions is used for OpenAI, Groq and xAI because it is the one interface all three share. Moving OpenAI and xAI to the Responses API is a follow-up.

SDK retries are disabled (`max_retries=0`). The job runner owns retries so that cancel, backoff and usage accounting stay in one place.

### 3. Capabilities are checked, never assumed
Each capability is stored with its source:
- `reported:*`: the provider's API said so;
- `documented:*`: the provider's docs state it for every local model (Ollama structured output);
- `declared:*`: the author entered it in AI settings;
- `unknown`.

Native structured output is used only for `reported`, `documented` or `declared` true. Otherwise the JSON schema goes into the prompt as text. Either way the reply is validated, and invalid JSON is a retryable `invalid_output` error.

### 4. Credentials
`security/secrets.py` selects a key store by `PBS_SECRET_BACKEND`:

| Backend | Behaviour |
|---|---|
| `auto` (default) / `keyring` | OS credential store through `keyring`, under service `PersonalBookStudio` and account `provider:<id>` |
| `dev-file` | Explicit opt-in for development machines without a credential store. Writes `runtime/dev-secrets.json` with a user-only ACL. The app shows a warning. `runtime/` is never backed up or exported |
| `memory` | Tests only |

If no store is available, keys can only come from `PBS_<KIND>_API_KEY` environment variables, and the UI warns about it.

The database holds only `credential_ref`. Keys arrive as `SecretStr` and are never returned by the API. A canary test scans the following for the key and expects zero hits:
- the DB and its WAL;
- logs;
- the backup ZIP and its entries;
- exports.

This replaces SECURITY §3's earlier "no plaintext file fallback". The Phase 03 brief asked for an explicit protected development fallback, and `dev-file` is that fallback.

### 5. Durable jobs on threads plus SQLite
`jobs/runner.py` runs a polling loop and a bounded `ThreadPoolExecutor`:
- 2 jobs at a time (`PBS_AI_WORKERS`);
- 1 at a time per local Ollama server.

Jobs move through their lifecycle like this:
- **Claiming** is one `BEGIN IMMEDIATE` transaction.
- **Leases** are extended while text streams in.
- **On startup**, `running` jobs are re-queued if attempts remain. Otherwise they are marked `interrupted`, or `cancelled` if a cancel was requested.
- **Cancel** sets an in-memory event (fast path) and a DB flag that the worker re-reads every second (works across processes). The stream is closed. Any text received so far is kept for inspection and is never applicable.
- **Retry** uses backoff: provider `Retry-After` if given, else `2^attempt` + jitter, capped. Errors are classified: `auth`, `quota`, `bad_request`, `refused` and `not_found` are final; `rate_limited`, `overloaded`, `timeout`, `connection`, `server_error` and `invalid_output` are retried. A manual Retry adds 3 attempts and keeps attempt numbers increasing.

Exactly-once is enforced in the database:
- `proposal.job_id` is UNIQUE;
- a partial UNIQUE index on `chapter_revision.accepted_proposal_id` means a proposal can become at most one revision, even with concurrent accepts (tested, including a double-click e2e);
- the final commit (usage record + proposal + job state) is one transaction, and a commit for a job no longer `running`, or with cancel requested, is discarded.

Asyncio workers (ARCHITECTURE §6) were not used: the SDKs' sync clients are simpler to cancel cooperatively from a thread, and SQLite is the real serialization point anyway. `job_step` is deferred to Phase 06; Phase 03 jobs are single-step.

### 6. Requests, review, accept
A request:
- names a task and either an explicit provider and model, or the task's route;
- has no hidden default: with no route and no choice, it is a 409 `model_not_chosen`;
- must be made against the saved head (an unsaved draft is a 409 "Save your changes first");
- is refused on approved chapters;
- includes only that chapter's text, clipped to 48,000 characters around the selection;
- wraps that text in a random-tag `<pbs-data-…>` envelope.

Accepting a suggestion:
- needs `expected_head_no` and no unsaved draft;
- checks applicability: a `replace_selection` proposal requires the original passage to be unchanged, and an `insert_at` proposal requires the head to be unchanged;
- creates an `ai_generated` revision, or `ai_assisted` when the author edited the text, with `accepted_proposal_id` set.

Stale proposals are computed when they are read, not stored. The "rebase" is to ask again.

### 7. Costs
Pricing:
- PBS ships **no prices**;
- the author enters prices per model, with a source URL and an "as of" date;
- local providers record cost `0` with the basis "no API charge";
- with no price, cost is `NULL` and shows as "Unknown". It is never guessed.

Before a job runs, the estimate gives:
- input tokens, at about 4 characters per token, labelled as an estimate;
- the output limit;
- with a price, an upper bound on the charge.

Usage after the run comes from the provider's reported counts and is marked as reported. `usage_record` is immutable (DB triggers).

## Consequences
- Adding a provider means a new adapter, an allowlist entry in `egress.CLOUD_HOSTS` and contract tests against recorded wire formats. The gate needs no changes.
- Live checks against real providers are a separate opt-in command (`python -m pbs_core.live_check`). The test suite's socket guard forbids them. The Ollama smoke test runs only when a local Ollama answers and `PBS_OLLAMA_MODEL` is set.

## Not verified / follow-ups
- OpenAI Responses usage field names; Gemini `RetryInfo` and pagination; the Groq streamed-usage location; the xAI error body and rate-limit headers.
- Real Ollama (not installed here) and real cloud calls (no keys used) have not been exercised. Contract tests use the documented wire formats.
- macOS Keychain has not been exercised.
