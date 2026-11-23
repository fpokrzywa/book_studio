import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { routes } from "../../app/routes";
import { axeViolations, mockApi, project, renderRoutes, systemInfo, type Handler } from "../../test/utils";

const P = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
const T = "2026-11-22T10:00:00.000Z";

const section = (over = {}) => ({
  id: "S1",
  ordinal: 1,
  title: "Why oil matters",
  goal: "Show the problem",
  target_words: 300,
  state: "done",
  output_md: "Section text.",
  summary: "Covers oil.",
  edited: false,
  reviewed: false,
  attempts: 1,
  job_ids: ["J1"],
  job_id: "J1",
  error: null,
  context: {
    budget_tokens: 5550,
    used_tokens: 900,
    is_estimate: true,
    parts: [
      { key: "brief", label: "Book brief", required: true, tokens: 120, status: "included" },
      { key: "so_far", label: "This chapter so far", required: false, tokens: 400, status: "trimmed" },
    ],
  },
  provenance: { model: "mock-writer", template: "section@1" },
  ...over,
});

const plan = (over = {}) => ({
  id: "PL1",
  chapter_id: "C1",
  chapter_title: "Foundations",
  run_id: "R1",
  status: "running",
  review_gate: "none",
  provider_label: "Built-in test model",
  provider_kind: "mock",
  model_name: "mock-writer",
  token_budget: 6000,
  max_output_tokens: 800,
  base_revision_no: 0,
  proposal_id: null,
  proposal_status: null,
  note: null,
  sections: [
    section(),
    section({
      id: "S2",
      ordinal: 2,
      title: "How to change it",
      state: "failed",
      output_md: null,
      error: "The test model failed on purpose (once).",
      attempts: 1,
    }),
  ],
  next_step: "A section failed. Retry it: finished sections are kept and not sent again.",
  created_at: T,
  updated_at: T,
  finished_at: null,
  ...over,
});

const qfinding = (over = {}) => ({
  id: "Q1",
  chapter_id: "C1",
  chapter_title: "Foundations",
  check: "unsupported_claim",
  check_label: "Factual-looking sentences without a citation",
  origin: "rule",
  severity: "warning",
  message: "This sentence states a fact (a percentage) but its paragraph has no citation.",
  excerpt: "In 2019, 64% of mower repairs were caused by old oil.",
  details: {},
  revision_no: 1,
  present: true,
  state: "open",
  note: null,
  updated_at: T,
  ...over,
});

function base(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/system/info": () => ({ json: systemInfo }),
    [`GET /api/projects/${P}`]: () => ({ json: project() }),
    [`GET /api/projects/${P}/chapters`]: () => ({ json: [] }),
    "GET /api/ai/providers": () => ({ json: [] }),
    ...extra,
  });
}

describe("Write: drafts", () => {
  it("shows each section's state and context, retries only the failed section and lists the job history", async () => {
    const { calls } = base({
      [`GET /api/projects/${P}/writing/plans`]: () => ({ json: [plan()] }),
      [`POST /api/projects/${P}/writing/plans/PL1/sections/S2/retry`]: () => ({ json: plan() }),
      [`GET /api/projects/${P}/writing/plans/PL1/history`]: () => ({
        json: [
          {
            job_id: "J1",
            section: "1. Why oil matters",
            attempt_no: 1,
            status: "succeeded",
            stage: "section_done",
            task: "draft",
            provider_kind: "mock",
            model_name: "mock-writer",
            template: "section@1",
            created_at: T,
            finished_at: T,
            error_message: null,
            input_tokens: 900,
            output_tokens: 120,
            cost: null,
            currency: null,
            logs: [
              { ts: T, level: "info", message: "Context for section 1 “Why oil matters”: about 900 tokens." },
            ],
          },
        ],
      }),
    });
    const { container } = renderRoutes(routes, `/projects/${P}/write`);
    const user = userEvent.setup();
    const card = await screen.findByRole("article", { name: "Foundations" });
    expect(within(card).getByText(/A section failed. Retry it/)).toBeInTheDocument();
    expect(within(card).getByText("The test model failed on purpose (once).")).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);

    await user.click(within(card).getByText("Text, summary and context"));
    expect(within(card).getByText(/about 900 of 5,550 tokens \(estimate\)/)).toBeInTheDocument();
    expect(within(card).getByRole("row", { name: /This chapter so far 400 trimmed/ })).toBeInTheDocument();

    expect(within(card).getAllByRole("button", { name: "Retry this section" })).toHaveLength(1);
    await user.click(within(card).getByRole("button", { name: "Retry this section" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/sections/S2/retry"))).toBe(true));

    await user.click(within(card).getByText("Job history for this draft"));
    expect(
      await within(card).findByText(/attempt 1: succeeded · draft · mock \/ mock-writer/),
    ).toBeInTheDocument();
    expect(within(card).getByText(/Context for section 1/)).toBeInTheDocument();
  });

  it("lets the author edit and approve a section at a review gate", async () => {
    const gated = plan({
      status: "awaiting_review",
      review_gate: "each_section",
      sections: [
        section(),
        section({ id: "S2", ordinal: 2, title: "Next", state: "pending", output_md: null }),
      ],
      next_step: "Review the finished section (edit it if you like) and approve it to continue.",
    });
    const { calls } = base({
      [`GET /api/projects/${P}/writing/plans`]: () => ({ json: [gated] }),
      [`POST /api/projects/${P}/writing/plans/PL1/sections/S1/approve`]: () => ({ json: gated }),
    });
    renderRoutes(routes, `/projects/${P}/write`);
    const user = userEvent.setup();
    const box = await screen.findByLabelText(/Section text \(edit before approving/);
    await user.clear(box);
    await user.type(box, "My version.");
    await user.click(screen.getByRole("button", { name: "Approve section and continue" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/approve"))?.body).toEqual({ edited_md: "My version." }),
    );
  });
});

describe("Write: quality", () => {
  it("runs the checks, says they are not proof, and records the author's decision", async () => {
    let findings = [qfinding()];
    const { calls } = base({
      [`GET /api/projects/${P}/writing/quality`]: () => ({ json: findings }),
      [`GET /api/projects/${P}/writing/settings`]: () => ({
        json: {
          code_check_authorized: false,
          code_check_note: "Code is never run.",
          similarity_provider: "No external similarity provider is configured.",
        },
      }),
      [`POST /api/projects/${P}/writing/quality/run`]: () => ({
        json: {
          checks_run: ["unsupported_claim"],
          checks_skipped: { code_syntax: "Not allowed for this book." },
          new: 1,
          seen: 0,
          findings,
          disclaimer: "These checks look for patterns. They do not decide whether a statement is true.",
        },
      }),
      [`PATCH /api/projects/${P}/writing/quality/Q1`]: (req) => {
        findings = [qfinding({ state: (req.body as { state: string }).state })];
        return { json: findings[0] };
      },
    });
    const { container } = renderRoutes(routes, `/projects/${P}/write?tab=quality`);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Run checks" }));
    expect(await screen.findByText(/They do not decide whether a statement is true/)).toBeInTheDocument();
    expect(screen.getByText(/code_syntax \(Not allowed for this book.\)/)).toBeInTheDocument();
    const group = screen.getByRole("region", { name: "Factual-looking sentences without a citation" });
    expect(
      within(group).getByText("In 2019, 64% of mower repairs were caused by old oil."),
    ).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);
    await user.selectOptions(within(group).getByLabelText("Your decision"), "needs_source");
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ state: "needs_source" }),
    );
  });
});
