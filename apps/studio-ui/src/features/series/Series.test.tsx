import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { routes } from "../../app/routes";
import { axeViolations, mockApi, project, renderRoutes, systemInfo, type Handler } from "../../test/utils";

const S = "01ARZ3NDEKTSV4RRFFQ69G5SER";
const B1 = "01ARZ3NDEKTSV4RRFFQ69G5BK1";
const B2 = "01ARZ3NDEKTSV4RRFFQ69G5BK2";
const C2 = "01ARZ3NDEKTSV4RRFFQ69G5CH2";
const T = "2026-11-23T10:00:00.000Z";

const series = {
  id: S,
  title: "Tides of Salt",
  description: "",
  books: [
    { project_id: B1, title: "The Salt Road", position: 1, language: "en" },
    { project_id: B2, title: "The Iron Tide", position: 2, language: "en" },
  ],
  counts: { entities: 2, suggested: 1, open_issues: 1 },
  updated_at: T,
};

const fact = (over = {}) => ({
  id: "F1",
  entity_id: "E1",
  attribute: "eye colour",
  value: "green",
  story_time: null,
  book_project_id: B1,
  book_title: "The Salt Road",
  status: "canon",
  origin: "author",
  provenance: {},
  superseded_by: null,
  updated_at: T,
  ...over,
});

const canon = {
  entities: [
    {
      id: "E1",
      kind: "character",
      name: "Mara",
      aliases: [],
      summary: "",
      status: "canon",
      origin: "author",
      provenance: {},
      facts: [
        fact(),
        fact({ id: "F2", attribute: "age", value: "30", status: "suggested", origin: "book_note" }),
      ],
      updated_at: T,
    },
    {
      id: "E2",
      kind: "character",
      name: "Jon",
      aliases: [],
      summary: "",
      status: "canon",
      origin: "author",
      provenance: {},
      facts: [],
      updated_at: T,
    },
  ],
  relationships: [
    {
      id: "R1",
      from_entity_id: "E2",
      to_entity_id: "E1",
      label: "brother",
      status: "canon",
      origin: "author",
      provenance: {},
    },
  ],
  chronology: [],
  chronology_warnings: [],
};

const issue = (over = {}) => ({
  id: "I1",
  project_id: B2,
  book_title: "The Iron Tide",
  chapter_id: C2,
  chapter_title: "Chapter One",
  revision_no: 1,
  rule: "trait",
  message: "Mara: canon says eye colour is “green”, but this sentence says “brown”.",
  excerpt: "Mara's brown eyes were wet.",
  start: 22,
  end: 49,
  found_value: "brown",
  entity_id: "E1",
  fact_id: "F1",
  relationship_id: null,
  present: true,
  state: "open",
  resolution_note: null,
  link: `/projects/${B2}/chapters/${C2}?select=22-49`,
  updated_at: T,
  ...over,
});

function base(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/system/info": () => ({ json: systemInfo }),
    [`GET /api/series/${S}`]: () => ({ json: series }),
    [`GET /api/series/${S}/canon`]: () => ({ json: canon }),
    [`GET /api/series/${S}/issues`]: () => ({ json: [issue()] }),
    "GET /api/projects": () => ({ json: { items: [project()], total: 1 } }),
    ...extra,
  });
}

describe("Series: continuity review", () => {
  it("links each contradiction to its passage and records the author's decision", async () => {
    const { calls } = base({
      [`POST /api/series/${S}/issues/I1/resolve`]: ({ body }) => ({
        json: issue({ state: "intended", resolution_note: (body as { note: string }).note }),
      }),
    });
    const { container } = renderRoutes(routes, `/series/${S}?tab=continuity`);
    const link = await screen.findByRole("link", { name: /Chapter One.*open the passage/ });
    expect(link.getAttribute("href")).toBe(`/projects/${B2}/chapters/${C2}?select=22-49`);
    expect(screen.getByText("Mara's brown eyes were wet.")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Note for your decision (optional)"), "Contact lenses.");
    await userEvent.click(screen.getByRole("button", { name: "Intended, leave it" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/issues/I1/resolve"))).toBe(true));
    const sent = calls.find((c) => c.path.endsWith("/issues/I1/resolve"));
    expect(sent?.body).toEqual({ action: "intended", note: "Contact lenses." });
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("Series: story bible", () => {
  it("separates AI or imported suggestions from approved canon", async () => {
    const { calls } = base({
      [`PATCH /api/series/${S}/facts/F2`]: () => ({
        json: fact({ id: "F2", attribute: "age", value: "30" }),
      }),
    });
    const { container } = renderRoutes(routes, `/series/${S}?tab=bible`);
    const table = await screen.findByRole("table", { name: "Facts about Mara" });
    const rows = within(table).getAllByRole("row");
    expect(within(rows[1]!).getByText("Canon")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("Suggestion, not canon yet")).toBeInTheDocument();
    await userEvent.click(within(rows[2]!).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ status: "canon" }));
    expect(await axeViolations(container)).toEqual([]);
  });

  it("shows relationships as text, with the map as an extra", async () => {
    base();
    renderRoutes(routes, `/series/${S}?tab=relationships`);
    const list = await screen.findByRole("heading", { name: "Who is who to whom" });
    expect(list.parentElement?.textContent).toContain("Jon is Mara's brother");
    expect(screen.getByRole("img", { name: /2 characters and 1 relationships/ })).toBeInTheDocument();
  });
});
