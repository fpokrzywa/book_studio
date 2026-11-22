import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { routes } from "../../app/routes";
import { axeViolations, mockApi, project, renderRoutes, systemInfo, type Handler } from "../../test/utils";

vi.mock("../editor/SourceEditor", async () => {
  const fake = await import("../../test/fakeSourceEditor");
  return { SourceEditor: fake.FakeSourceEditor };
});

const P = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
const C = "01ARZ3NDEKTSV4RRFFQ69G5FAX";
const PROV = "01ARZ3NDEKTSV4RRFFQ69G5FB0";
const base = `/api/projects/${P}/chapters/${C}`;
const T = "2026-11-22T10:00:00.000Z";

const chapter = {
  id: C,
  project_id: P,
  parent_id: null,
  depth: 0,
  kind: "chapter",
  position: "V",
  title: "Chapter One",
  slug: "chapter-one",
  status: "draft",
  locked: false,
  target_word_count: null,
  head_revision_id: "R1",
  head_revision_no: 1,
  word_count: 2,
  created_at: T,
  updated_at: T,
};
const content = (no: number, source_md: string) => ({
  chapter_id: C,
  revision_id: `R${no}`,
  revision_no: no,
  source_md,
  word_count: 2,
  saved_at: T,
  draft: null,
});
const ollama = {
  id: PROV,
  kind: "ollama",
  label: "Ollama (local)",
  base_url: "http://127.0.0.1:11434",
  local: true,
  enabled: true,
  key_status: "not_needed",
  health: null,
  created_at: T,
  models: [
    {
      name: "gemma4:4b",
      display_name: null,
      context_tokens: 131072,
      max_output_tokens: null,
      capabilities: { chat: "reported:true", structured_output: "documented:true" },
      source: "discovered",
      updated_at: T,
    },
  ],
};
const job = (over = {}) => ({
  id: "J1",
  project_id: P,
  project_title: "The Quiet Engine",
  chapter_id: C,
  chapter_title: "Chapter One",
  task: "draft",
  provider_id: PROV,
  provider_kind: "ollama",
  provider_label: "Ollama (local)",
  provider_local: true,
  model_name: "gemma4:4b",
  status: "queued",
  stage: "queued",
  received_chars: null,
  attempt: 0,
  max_attempts: 3,
  run_after: T,
  cancel_requested: false,
  error_code: null,
  error_message: null,
  partial_output: null,
  proposal_id: null,
  estimate: {},
  created_at: T,
  started_at: null,
  finished_at: null,
  ...over,
});
const proposal = {
  id: "PR1",
  job_id: "J1",
  project_id: P,
  chapter_id: C,
  mode: "append",
  status: "pending",
  base_revision_no: 1,
  current_head_no: 1,
  applicable: true,
  not_applicable_reason: null,
  selection_start: null,
  selection_end: null,
  original_text: null,
  payload_md: "The night shift arrived.",
  accepted_revision_no: null,
  provenance: {
    provider_kind: "ollama",
    provider_label: "Ollama (local)",
    model: "gemma4:4b",
    task: "draft",
  },
  created_at: T,
  decided_at: null,
};
const estimate = {
  provider_id: PROV,
  provider_label: "Ollama (local)",
  provider_local: true,
  model_name: "gemma4:4b",
  input_tokens: 120,
  max_output_tokens: 2048,
  is_estimate: true,
  basis: "Estimate",
  cost_upper_bound: "0",
  currency: null,
  cost_note: "Local model: no API charge.",
  context_clipped: false,
  blocked_reason: null,
};

function editorApi(extra: Record<string, Handler> = {}) {
  let proposals: unknown[] = [];
  let head = content(1, "Old text.");
  const api = mockApi({
    "GET /api/system/info": () => ({ json: systemInfo }),
    [`GET /api/projects/${P}`]: () => ({ json: project() }),
    [`GET ${base}`]: () => ({ json: chapter }),
    [`GET ${base}/content`]: () => ({ json: head }),
    [`GET /api/projects/${P}/chapters`]: () => ({ json: [chapter] }),
    [`GET /api/projects/${P}/proposals`]: () => ({ json: proposals }),
    "GET /api/ai/providers": () => ({ json: [ollama] }),
    "GET /api/ai/routes": () => ({ json: [] }),
    "GET /api/ai/jobs": () => ({ json: [] }),
    [`GET /api/projects/${P}/knowledge`]: () => ({
      json: { project_library: null, linked: [], available_shared: [], usable_source_count: 0 },
    }),
    "GET /api/voice/profiles": () => ({ json: [] }),
    [`POST /api/projects/${P}/ai/estimate`]: () => ({ json: estimate }),
    [`POST /api/projects/${P}/ai/jobs`]: () => {
      proposals = [proposal];
      return { status: 202, json: job() };
    },
    [`POST /api/projects/${P}/proposals/PR1/accept`]: () => {
      head = content(2, "Old text.\n\nThe night shift arrived.\n");
      proposals = [];
      return {
        json: { proposal: { ...proposal, status: "accepted" }, save: { created: true, content: head } },
      };
    },
    ...extra,
  });
  return api;
}

beforeEach(() => {
  localStorage.setItem("pbs.editor.view", "write");
  localStorage.removeItem("pbs.editor.ai");
});

describe("AI assist in the editor", () => {
  it("asks a local model, shows the suggestion for review, and accepts it as a new revision", async () => {
    const { calls } = editorApi();
    const { container } = renderRoutes(routes, `/projects/${P}/chapters/${C}`);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /AI assist/ }));
    const panel = await screen.findByRole("region", { name: "AI assist" });

    await user.selectOptions(within(panel).getByLabelText("Model"), `${PROV}::gemma4:4b`);
    expect(within(panel).getByText(/On this computer/)).toBeInTheDocument();
    await user.type(within(panel).getByLabelText("What should it do?"), "One paragraph.");
    expect(await within(panel).findByText(/no API charge/i)).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Ask" }));

    const post = calls.find((c) => c.method === "POST" && c.path.endsWith("/ai/jobs"));
    expect(post?.body).toMatchObject({
      chapter_id: C,
      task: "draft",
      instruction: "One paragraph.",
      mode: "append",
      base_revision_no: 1,
      provider_id: PROV,
      model_name: "gemma4:4b",
    });

    const card = await screen.findByRole("article", { name: /Draft by gemma4:4b/ });
    expect(within(card).getByLabelText(/Suggested text/)).toHaveValue("The night shift arrived.");
    expect(screen.getByLabelText("Chapter text (Markdown)")).toHaveValue("Old text."); // nothing applied yet
    expect(await axeViolations(container)).toEqual([]);

    await user.click(within(card).getByRole("button", { name: "Accept as a new revision" }));
    const accept = calls.find((c) => c.path.endsWith("/accept"));
    expect(accept?.body).toEqual({ expected_head_no: 1 });
    await waitFor(() =>
      expect(screen.getByLabelText("Chapter text (Markdown)")).toHaveValue(
        "Old text.\n\nThe night shift arrived.\n",
      ),
    );
    expect(screen.getByText(/^Saved as revision 2/)).toBeInTheDocument();
    expect(screen.getByText("Accepted. Saved as revision 2.")).toBeInTheDocument(); // announced
  });

  it("sends the author's edited text when it differs from the suggestion", async () => {
    const { calls } = editorApi({ [`GET /api/projects/${P}/proposals`]: () => ({ json: [proposal] }) });
    renderRoutes(routes, `/projects/${P}/chapters/${C}`);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Review" }));
    const box = await screen.findByLabelText(/Suggested text/);
    await user.clear(box);
    await user.type(box, "My version.");
    await user.click(screen.getByRole("button", { name: "Accept as a new revision" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/accept"))).toBe(true));
    expect(calls.find((c) => c.path.endsWith("/accept"))?.body).toEqual({
      expected_head_no: 1,
      edited_md: "My version.",
    });
  });

  it("asks the author to save before running or accepting while there are unsaved changes", async () => {
    editorApi({ [`GET /api/projects/${P}/proposals`]: () => ({ json: [proposal] }) });
    renderRoutes(routes, `/projects/${P}/chapters/${C}`);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Chapter text (Markdown)"), " more");
    await user.click(screen.getByRole("button", { name: /AI assist/ }));
    expect(await screen.findByText(/Save your changes first/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save your changes to accept" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept as a new revision" })).toBeNull();
  });

  it("explains a blocked cloud request instead of sending it", async () => {
    editorApi({
      [`POST /api/projects/${P}/ai/estimate`]: () => ({
        json: {
          ...estimate,
          provider_local: false,
          provider_label: "OpenAI",
          cost_upper_bound: null,
          blocked_reason: "Local-only mode is on, so OpenAI cannot be used. Nothing was sent.",
        },
      }),
    });
    renderRoutes(routes, `/projects/${P}/chapters/${C}`);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /AI assist/ }));
    await user.selectOptions(await screen.findByLabelText("Model"), `${PROV}::gemma4:4b`);
    expect(await screen.findByText(/Nothing was sent/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
  });
});

describe("AI settings", () => {
  const status = {
    privacy_mode: "local_only",
    external_requests: {},
    active_cloud_calls: {},
    queued_jobs: 0,
    running_jobs: 0,
    pending_proposals: 0,
    secret_store: { backend: "keyring", secure: true, writable: true, warning: null },
  };
  const kinds = [
    {
      kind: "ollama",
      label: "Ollama (local)",
      local: true,
      needs_key: false,
      default_url: "http://127.0.0.1:11434",
      url_editable: true,
      note: "Runs models on this computer.",
    },
    {
      kind: "openai",
      label: "OpenAI",
      local: false,
      needs_key: true,
      default_url: "https://api.openai.com/v1",
      url_editable: false,
      note: "Cloud.",
    },
  ];

  it("requires confirmation before allowing cloud AI and tests a provider", async () => {
    const { calls } = mockApi({
      "GET /api/system/info": () => ({ json: systemInfo }),
      "GET /api/ai/status": () => ({ json: status }),
      "GET /api/ai/providers": () => ({ json: [ollama] }),
      "GET /api/ai/provider-kinds": () => ({ json: kinds }),
      "GET /api/ai/routes": () => ({ json: [] }),
      "PUT /api/ai/privacy": () => ({ json: { ...status, privacy_mode: "cloud_allowed" } }),
      [`POST /api/ai/providers/${PROV}/test`]: () => ({
        json: { ok: true, message: "Ollama 0.12.6 is running locally.", checked_at: T },
      }),
    });
    const { container } = renderRoutes(routes, "/ai-settings");
    const user = userEvent.setup();
    expect(await screen.findByRole("heading", { name: "AI settings" })).toBeInTheDocument();
    expect(screen.getByText("none")).toBeInTheDocument(); // no internet requests
    expect(await axeViolations(container)).toEqual([]);

    await user.click(screen.getByLabelText(/Cloud allowed/));
    const dialog = await screen.findByRole("alertdialog", { name: "Allow cloud AI?" });
    expect(calls.some((c) => c.path === "/api/ai/privacy")).toBe(false);
    await user.click(within(dialog).getByRole("button", { name: "Allow cloud AI" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/api/ai/privacy")?.body).toEqual({
        mode: "cloud_allowed",
        confirm: true,
      }),
    );

    await user.click(screen.getByRole("button", { name: "Test connection" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/test"))).toBe(true));
  });
});

describe("AI jobs status center", () => {
  it("shows stages, actionable failures with retry, and unknown costs", async () => {
    const { calls } = mockApi({
      "GET /api/system/info": () => ({ json: systemInfo }),
      "GET /api/ai/jobs": () => ({
        json: [
          job({
            status: "failed",
            stage: "failed",
            attempt: 1,
            error_code: "auth",
            error_message: "The provider rejected the API key. Check it in AI settings.",
          }),
        ],
      }),
      "GET /api/ai/usage": () => ({
        json: {
          rows: [
            {
              id: "U1",
              job_id: "J0",
              project_id: P,
              project_title: "The Quiet Engine",
              provider_kind: "openai",
              model_name: "gpt-x",
              input_tokens: 11,
              output_tokens: 2,
              reported_by_provider: true,
              cost_amount: null,
              currency: null,
              price_basis: "Unknown: no price entered for this model.",
              attempt: 1,
              created_at: T,
            },
          ],
          totals: [{ currency: null, amount: null, calls: 1, unknown_cost_calls: 1 }],
        },
      }),
      "POST /api/ai/jobs/J1/retry": () => ({ json: job({ status: "queued" }) }),
    });
    const { container } = renderRoutes(routes, "/jobs");
    const user = userEvent.setup();
    expect(await screen.findByText(/rejected the API key/)).toBeInTheDocument();
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(screen.queryByText(/%/)).toBeNull(); // no invented percentages
    expect(await axeViolations(container)).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/ai/jobs/J1/retry")).toBe(true));
  });
});

describe("Sources on a suggestion", () => {
  it("shows the passages behind each paragraph, flags unverified ones and removed citations", async () => {
    const cited = {
      ...proposal,
      payload_md: "Bolts go in a spiral [@torque-handbook, para. 2].\n\nA paragraph with no source.",
      provenance: {
        ...proposal.provenance,
        knowledge: {
          dropped_labels: ["S9"],
          paragraphs: [
            {
              index: 0,
              preview: "Bolts go in a spiral.",
              status: "supported",
              dropped_labels: ["S9"],
              supports: [
                {
                  label: "S1",
                  kind: "source",
                  title: "torque-handbook",
                  quote: "Cylinder head bolts are tightened in a spiral pattern.",
                  located: true,
                  source_id: "SRC1",
                  chunk_id: "CH1",
                  citation_key: "torque-handbook",
                  locator: "para. 2",
                },
              ],
            },
            {
              index: 1,
              preview: "A paragraph with no source.",
              status: "unverified",
              supports: [],
              dropped_labels: [],
            },
          ],
        },
      },
    };
    editorApi({ [`GET /api/projects/${P}/proposals`]: () => ({ json: [cited] }) });
    const { container } = renderRoutes(routes, `/projects/${P}/chapters/${C}`);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Review" }));
    const box = await screen.findByRole("region", { name: "Sources for each paragraph" });
    expect(within(box).getByRole("link", { name: "torque-handbook, para. 2" })).toHaveAttribute(
      "href",
      "/knowledge/sources/SRC1?passage=CH1",
    );
    expect(
      within(box).getByText("Cylinder head bolts are tightened in a spiral pattern."),
    ).toBeInTheDocument();
    expect(within(box).getByText(/Unverified: no source supports this paragraph/)).toBeInTheDocument();
    expect(within(box).getByText(/cited passages it was never given \(S9\)/)).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);
  });
});
