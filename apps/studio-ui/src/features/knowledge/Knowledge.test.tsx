import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { routes } from "../../app/routes";
import { axeViolations, mockApi, project, renderRoutes, systemInfo } from "../../test/utils";

const P = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
const S = "01ARZ3NDEKTSV4RRFFQ69G5FB1";
const T = "2026-11-22T10:00:00.000Z";

const source = (over = {}) => ({
  id: S,
  library_id: "L1",
  library_name: "Sources for The Quiet Engine",
  kind: "markdown",
  title: "torque-handbook",
  title_origin: "file_name",
  citation_key: "torque-handbook",
  original_name: "torque-handbook.md",
  file_sha256: "a".repeat(64),
  byte_size: 400,
  tags: [],
  enabled: true,
  status: "indexed",
  error: null,
  warnings: [],
  chunk_count: 3,
  word_count: 90,
  page_count: null,
  authors: [],
  year: null,
  publisher: null,
  url: null,
  doi: null,
  created_at: T,
  indexed_at: T,
  removed_at: null,
  ...over,
});
const book = {
  project_library: {
    id: "L1",
    name: "Sources",
    scope: "project",
    project_id: P,
    description: null,
    source_count: 1,
    linked_project_ids: [],
    created_at: T,
  },
  linked: [],
  available_shared: [
    {
      id: "L2",
      name: "Engine references",
      scope: "shared",
      project_id: null,
      description: null,
      source_count: 4,
      linked_project_ids: [],
      created_at: T,
    },
  ],
  usable_source_count: 1,
};
const hit = {
  chunk_id: "C1",
  source_id: S,
  source_title: "torque-handbook",
  citation_key: "torque-handbook",
  locator: "para. 2",
  heading_path: "Fasteners",
  snippet: [
    { text: "Bolts are tightened in a ", hit: false },
    { text: "spiral", hit: true },
    { text: " <script>alert(1)</script> pattern.", hit: false },
  ],
  reasons: ["Passage contains: spiral"],
  score: 2.1,
};

describe("Book sources", () => {
  it("lists sources, toggles AI use, opts in to shared libraries, and shows search hits as text", async () => {
    const { calls } = mockApi({
      "GET /api/system/info": () => ({ json: systemInfo }),
      [`GET /api/projects/${P}`]: () => ({ json: project() }),
      [`GET /api/projects/${P}/knowledge`]: () => ({ json: book }),
      [`GET /api/projects/${P}/knowledge/sources`]: () => ({ json: [source()] }),
      [`PATCH /api/knowledge/sources/${S}`]: ({ body }) => ({ json: source(body as object) }),
      [`PUT /api/projects/${P}/knowledge/links/L2`]: () => ({
        json: { ...book, linked: book.available_shared, available_shared: [] },
      }),
      [`GET /api/projects/${P}/knowledge/search`]: () => ({
        json: {
          query: "spiral",
          mode: "all",
          hits: [hit],
          searched_sources: 1,
          semantic: "unavailable",
          semantic_note: "Word matching only.",
        },
      }),
    });
    const { container } = renderRoutes(routes, `/projects/${P}/knowledge`);
    const user = userEvent.setup();
    expect(await screen.findByRole("heading", { name: "Sources", level: 1 })).toBeInTheDocument();
    expect(screen.getByText(/@torque-handbook/)).toBeInTheDocument();
    expect(screen.getByText(/Title from the file name/)).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);

    await user.click(screen.getByLabelText("Use for AI"));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ enabled: false }));

    await user.click(screen.getByLabelText(/Engine references/));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "PUT" && c.path.endsWith("/links/L2"))).toBe(true),
    );

    await user.type(screen.getByLabelText("Search words"), "spiral");
    await user.click(screen.getByRole("button", { name: "Search" }));
    const result = await screen.findByText("spiral", { selector: "mark" });
    expect(result).toBeInTheDocument();
    // Source text is rendered as text: the script tag is visible characters, not an element.
    expect(container.querySelector(".hits script")).toBeNull();
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument();
    const hitList = container.querySelector(".hits") as HTMLElement;
    expect(within(hitList).getByRole("link", { name: "torque-handbook" }).getAttribute("href")).toBe(
      `/knowledge/sources/${S}?passage=C1`,
    );
    expect(screen.getByText(/Why it matched: Passage contains: spiral/)).toBeInTheDocument();
  });
});

describe("Source passages", () => {
  it("highlights the cited passage and edits only author-entered metadata", async () => {
    const { calls } = mockApi({
      "GET /api/system/info": () => ({ json: systemInfo }),
      [`GET /api/knowledge/sources/${S}/text`]: () => ({
        json: {
          source: source(),
          chunks: [
            { id: "C0", seq: 0, heading_path: "Fasteners", locator: "para. 1", text: "First passage." },
            { id: "C1", seq: 1, heading_path: "Fasteners", locator: "para. 2", text: "Cited passage." },
          ],
        },
      }),
      [`PATCH /api/knowledge/sources/${S}`]: ({ body }) => ({ json: source(body as object) }),
    });
    const { container } = renderRoutes(routes, `/knowledge/sources/${S}?passage=C1`);
    const user = userEvent.setup();
    const cited = await screen.findByRole("article", { name: /para. 2, cited passage/ });
    expect(cited).toHaveAttribute("data-target", "true");
    expect(screen.getByText(/never guesses an author/)).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);
    await user.type(screen.getByLabelText("Year"), "2024");
    await user.click(screen.getByRole("button", { name: "Save details" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toMatchObject({
        year: "2024",
        authors: [],
        doi: null,
      }),
    );
  });
});

describe("Interview", () => {
  it("saves the author's exact words", async () => {
    const q = {
      id: "Q1",
      seq: 0,
      prompt: "What first drew you to this subject?",
      origin: "bank",
      answer: null,
      history: [],
    };
    const { calls } = mockApi({
      "GET /api/system/info": () => ({ json: systemInfo }),
      [`GET /api/projects/${P}`]: () => ({ json: project() }),
      [`GET /api/projects/${P}/interview`]: () => ({
        json: { session_id: "I", project_id: P, title: "Interview", questions: [q], answered: 0 },
      }),
      [`PUT /api/projects/${P}/interview/questions/Q1/answer`]: ({ body }) => ({
        json: {
          session_id: "I",
          project_id: P,
          title: "Interview",
          answered: 1,
          questions: [
            {
              ...q,
              answer: {
                id: "A1",
                answer_text: (body as { answer_text: string }).answer_text,
                answered_at: T,
                supersedes_id: null,
              },
              history: [],
            },
          ],
        },
      }),
    });
    const { container } = renderRoutes(routes, `/projects/${P}/interview`);
    const user = userEvent.setup();
    const box = await screen.findByLabelText("What first drew you to this subject?");
    expect(await axeViolations(container)).toEqual([]);
    await user.type(box, "My grandfather's shed,  1998.");
    await user.click(screen.getByRole("button", { name: "Save answer" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
        answer_text: "My grandfather's shed,  1998.",
      }),
    );
  });
});

describe("Author voice", () => {
  it("requires the rights confirmation before a sample can be added", async () => {
    const profile = {
      id: "V1",
      name: "Sam",
      kind: "author",
      style_guide_md: "",
      guide_edited: false,
      metrics: {},
      labels: {},
      examples: [],
      corrections: [],
      samples: [],
      analysis_note: null,
      analyzed_at: null,
      created_at: T,
    };
    const { calls } = mockApi({
      "GET /api/system/info": () => ({ json: systemInfo }),
      "GET /api/voice/profiles": () => ({ json: [profile] }),
      "POST /api/voice/profiles/V1/samples": ({ body }) => ({
        status: 201,
        json: {
          ...profile,
          samples: [
            {
              id: "S",
              title: (body as { title: string }).title,
              word_count: 3,
              rights_basis: "own_writing",
              excerpt: "x",
              created_at: T,
            },
          ],
        },
      }),
    });
    const { container } = renderRoutes(routes, "/voice");
    const user = userEvent.setup();
    const panel = await screen.findByRole("region", { name: /Sam/ });
    await user.type(within(panel).getByLabelText("Text"), "My own words here.");
    const add = within(panel).getByRole("button", { name: "Add sample" });
    expect(add).toBeDisabled();
    expect(await axeViolations(container)).toEqual([]);
    await user.click(within(panel).getByLabelText(/I confirm this is my own writing/));
    await user.click(add);
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
        rights_confirmed: true,
        rights_basis: "own_writing",
      }),
    );
  });
});
