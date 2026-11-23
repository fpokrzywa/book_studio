import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { routes } from "../../app/routes";
import { axeViolations, mockApi, project, renderRoutes, systemInfo, type Handler } from "../../test/utils";

const P = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
const T = "2026-11-22T10:00:00.000Z";
const brief = {
  project_id: P,
  kind: "nonfiction",
  genre: null,
  purpose: "Help owners",
  promise: "Keep engines running",
  tone: null,
  author_profile_id: null,
  desired_chapters: 3,
  approval_preference: "review_each_chapter",
  budget_cap: null,
  budget_currency: null,
  max_chapters_per_run: 10,
  words_per_hour: 500,
  target_reader: null,
  exclusions: [],
  value_proposition: null,
  arc_md: null,
  arc_label: "Teaching arc",
  assumptions: [],
  status: "draft",
  version: 1,
  approved_at: null,
  updated_at: T,
};
const finding = (over = {}) => ({
  id: "F1",
  kind: "keyword",
  origin: "ai_brainstorm",
  evidence: "heuristic",
  text: "small engine care",
  provider: null,
  source_title: null,
  source_url: null,
  source_date: null,
  retrieved_at: null,
  meta: {},
  metrics: {},
  flags: ["ai_brainstorm_not_measured", "removed_unsupported_metric", "no_search_volume_data"],
  selected: false,
  archived: false,
  created_at: T,
  updated_at: T,
  ...over,
});
const node = (id: string, title: string) => ({
  id,
  kind: "chapter",
  title,
  goal: "A goal",
  target_words: 3000,
  locked: false,
  notes: "",
  requirements: { citations_min: 1, source_ids: [], notes: [] },
  children: [],
});
const outline = (over = {}) => ({
  id: "O1",
  version_no: 1,
  status: "proposed",
  origin: "ai_generated",
  nodes: [node("n_1", "Foundations"), node("n_2", "Practice")],
  totals: {
    chapters: 2,
    sections: 0,
    target_words: 6000,
    estimated_writing_hours: 12,
    writing_hours_basis: "Estimate: 500 drafted words per hour.",
  },
  based_on_id: null,
  brief_version: 1,
  research_ids: [],
  job_id: "J1",
  provenance: {},
  note: null,
  approved_at: null,
  applied_at: null,
  apply_report: null,
  created_at: T,
  updated_at: T,
  ...over,
});

function base(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/system/info": () => ({ json: systemInfo }),
    [`GET /api/projects/${P}`]: () => ({ json: project() }),
    [`GET /api/projects/${P}/brief`]: () => ({ json: brief }),
    "GET /api/ai/providers": () => ({ json: [] }),
    "GET /api/ai/jobs": () => ({ json: [] }),
    [`GET /api/projects/${P}/outlines`]: () => ({ json: [] }),
    [`GET /api/projects/${P}/research/findings`]: () => ({ json: [] }),
    ...extra,
  });
}

describe("Plan: research", () => {
  it("keeps measured evidence apart from heuristic ideas and explains removed market claims", async () => {
    base({
      [`GET /api/projects/${P}/research/findings`]: () => ({
        json: [
          finding(),
          finding({
            id: "F2",
            kind: "measured",
            origin: "author",
            evidence: "measured",
            text: "61% skip maintenance.",
            source_title: "Owners Survey",
            source_url: "https://example.org/s",
            source_date: "2025-03",
            flags: [],
          }),
        ],
      }),
      "GET /api/research/providers": () => ({
        json: [
          {
            kind: "openlibrary",
            label: "Open Library (public book metadata)",
            enabled: false,
            sends: "",
            available: false,
            unavailable_reason: null,
          },
        ],
      }),
      [`POST /api/projects/${P}/research/search`]: () => ({
        status: 409,
        json: {
          type: "x",
          title: "Open Library (public book metadata) is not turned on. Nothing was searched.",
          status: 409,
          code: "research_unavailable",
          reason: "not_configured",
        },
      }),
    });
    const { container } = renderRoutes(routes, `/projects/${P}/plan?tab=research`);
    const user = userEvent.setup();
    const evidence = await screen.findByRole("region", { name: "Measured evidence" });
    expect(await within(evidence).findByText("61% skip maintenance.")).toBeInTheDocument();
    expect(within(evidence).queryByText("small engine care")).toBeNull();
    const ideas = screen.getByRole("region", { name: /heuristic/ });
    expect(within(ideas).getByText("small engine care")).toBeInTheDocument();
    expect(within(ideas).getByText(/A sales, ranking or demand claim was removed/)).toBeInTheDocument();
    expect(within(ideas).getByText(/No search-volume data/)).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);

    await user.type(screen.getByLabelText("Search words"), "engines");
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText(/is not turned on. Nothing was searched/)).toBeInTheDocument();
  });
});

describe("Plan: outline", () => {
  it("approves an AI proposal and applies the approved outline", async () => {
    let versions = [outline()];
    const { calls } = base({
      [`GET /api/projects/${P}/outlines`]: () => ({ json: versions }),
      [`POST /api/projects/${P}/outlines/O1/approve`]: () => {
        versions = [outline({ status: "approved", approved_at: T })];
        return { json: versions[0] };
      },
      [`POST /api/projects/${P}/outlines/O1/apply`]: () => {
        const report = {
          created: ["Foundations", "Practice"],
          updated: [],
          restored: [],
          unchanged: 0,
          skipped_locked: [],
          kept_not_in_outline: [],
          archived_empty: [],
          manual_kept: [],
        };
        versions = [outline({ status: "approved", approved_at: T, applied_at: T, apply_report: report })];
        return { json: { outline: versions[0], report } };
      },
    });
    const { container } = renderRoutes(routes, `/projects/${P}/plan?tab=outline`);
    const user = userEvent.setup();
    const proposal = await screen.findByRole("region", { name: "AI proposal, version 1" });
    expect(within(proposal).getByText(/2 chapters, 6,000 target words, about 12 hours/)).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);
    await user.click(within(proposal).getByRole("button", { name: "Approve this outline" }));
    const approved = await screen.findByRole("region", { name: "Approved outline, version 1" });
    await user.click(within(approved).getByRole("button", { name: "Apply to manuscript" }));
    expect(await screen.findByText("New empty chapters")).toBeInTheDocument();
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual(
      expect.arrayContaining([
        `POST /api/projects/${P}/outlines/O1/approve`,
        `POST /api/projects/${P}/outlines/O1/apply`,
      ]),
    );
  });
});

describe("Plan: drafting", () => {
  it("shows the estimate as an estimate and refuses a run over the budget cap", async () => {
    base({
      [`GET /api/projects/${P}/chapters`]: () => ({ json: [] }),
      [`GET /api/projects/${P}/runs`]: () => ({ json: [] }),
      [`POST /api/projects/${P}/runs/estimate`]: () => ({
        json: {
          mode: "entire_book",
          provider_label: "OpenAI",
          model_name: "gpt-x",
          provider_local: false,
          chapters: [
            {
              chapter_id: "C1",
              title: "Foundations",
              eligible: true,
              reason: null,
              target_words: 3000,
              input_tokens: 4000,
              max_output_tokens: 4700,
            },
          ],
          eligible_count: 1,
          chapter_limit: 10,
          is_estimate: true,
          cost_upper_bound: "0.18",
          currency: "USD",
          cost_note: "Upper bound if the full output limit is used.",
          minutes_estimate: null,
          time_note: "No timing history for this model yet, so time is unknown.",
          budget_cap: "0.10",
          budget_currency: "USD",
          blocked_reason: "The estimated cost (up to 0.18 USD) is above the budget cap of 0.10 USD.",
        },
      }),
    });
    const { container } = renderRoutes(routes, `/projects/${P}/plan?tab=draft`);
    const user = userEvent.setup();
    await user.click(await screen.findByLabelText("Every eligible chapter"));
    await user.click(screen.getByRole("button", { name: "Estimate" }));
    expect(await screen.findByText(/Up to 0.18 USD/)).toBeInTheDocument();
    expect(screen.getByText(/time is unknown/)).toBeInTheDocument();
    expect(screen.getByText(/above the budget cap of 0.10 USD/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start drafting/ })).toBeDisabled();
    await waitFor(async () => expect(await axeViolations(container)).toEqual([]));
  });
});
