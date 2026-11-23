import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { routes } from "../../app/routes";
import { axeViolations, mockApi, project, renderRoutes, systemInfo, type Handler } from "../../test/utils";

const P = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
const T = "2026-11-22T10:00:00.000Z";

const profile = {
  template: "technical_manual",
  trim: "6x9",
  ink_paper: "bw_white",
  matter: [{ kind: "title_page", enabled: true, title: "Title page", body_md: "" }],
  copyright: {},
  metadata: { keywords: [], categories: [], ai_disclosure: { text: "", images: "", translation: "" } },
  cover: { layers: [{ role: "title", text: "The Quiet Engine", size_pt: 34, y: 0.2 }] },
  index_terms: [],
  options: {
    templates: { technical_manual: { label: "Technical manual", trim: "7x10" } },
    trims: { "6x9": { width_in: "6", height_in: "9", pages: { bw_white: [24, 828] } } },
    ink_paper: { bw_white: "Black ink, white paper" },
    matter_kinds: { title_page: { position: "front", title: "Title page", generated: true } },
  },
  rules: {
    ruleset: "kdp-paperback-2026-11-22",
    checked_on: "2026-11-22",
    sources: { paperback_cover: "https://kdp.amazon.com/en_US/help/topic/G201953020" },
    not_published: ["The exact position of KDP's barcode area."],
    ai_definitions: { ai_generated: "Generated.", ai_assisted: "Assisted." },
  },
  tools: {
    epubcheck: "unavailable",
    epubcheck_note: "Install EPUBCheck.",
    image_generation: "Not configured.",
    mobi: "Not built.",
  },
  ai_evidence: { ai_revisions: 0 },
  updated_at: T,
};

const pub = (over = {}) => ({
  id: "PK1",
  kind: "package",
  status: "succeeded",
  package_id: "PK1",
  file_name: "the-quiet-engine-kdp-package.zip",
  sha256: "abc",
  byte_size: 1000,
  page_count: 17,
  template: "technical_manual",
  trim: "6x9",
  ink_paper: "bw_white",
  ruleset: "kdp-paperback-2026-11-22",
  settings: {},
  report_summary: { pass: 40, fail: 1, manual: 6, unavailable: 1 },
  fidelity: "degraded",
  error: null,
  created_at: T,
  ...over,
});

function base(extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/system/info": () => ({ json: systemInfo }),
    [`GET /api/projects/${P}`]: () => ({ json: project() }),
    [`GET /api/projects/${P}/publishing/profile`]: () => ({ json: profile }),
    [`GET /api/projects/${P}/publishing/publications`]: () => ({ json: [pub()] }),
    ...extra,
  });
}

describe("Publish: package", () => {
  it("opens the preflight report and never calls missing EPUB validation a pass", async () => {
    base();
    const { container } = renderRoutes(routes, `/projects/${P}/publish?tab=package`);
    const report = await screen.findByRole("link", { name: "Open the preflight report" });
    expect(report.getAttribute("href")).toContain("package-file?name=preflight-report.html&inline=true");
    expect(screen.getByText(/40 passed, 1 failed, 6 check by hand, 1 could not check/)).toBeInTheDocument();
    expect(screen.getByText(/never as passed/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing is uploaded or published/)).toBeInTheDocument();
    expect(screen.getAllByText("kdp-paperback-2026-11-22", { selector: "strong" }).length).toBeGreaterThan(0);
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("Publish: build and preview", () => {
  it("says when the reading preview differs from the last export", async () => {
    base({
      [`GET /api/projects/${P}/publishing/preview/html`]: () => ({
        json: {
          html: "<p>Book</p>",
          sha256: "x",
          identical_to_last_export: false,
          note: "Not identical to your last HTML export: the book or settings changed since.",
        },
      }),
    });
    renderRoutes(routes, `/projects/${P}/publish?tab=build`);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Show reading preview" }));
    expect(await screen.findByText(/Not identical to your last HTML export/)).toBeInTheDocument();
    expect(screen.getByTitle("Reading preview of the book")).toHaveAttribute("sandbox", "");
    expect(screen.getByText(/they are not the PDF file/)).toBeInTheDocument();
  });
});

describe("Publish: cover", () => {
  it("shows the size from the final page count and flags a stale cover", async () => {
    base({
      [`GET /api/projects/${P}/publishing/cover-spec`]: () => ({
        json: {
          spec: {
            page_count: 120,
            spine_width_in: "0.2702",
            cover_width_in: "12.5202",
            cover_height_in: "9.2500",
            bleed_in: "0.125",
            spine_text_allowed: true,
          },
          based_on_pdf: { publication_id: "PDF2", page_count: 120, built_at: T },
          latest_cover: { publication_id: "C1", page_count: 96, stale: true, built_at: T },
          message:
            "Sized from the final page count of the latest print PDF. The last cover was built for a different page count: build it again.",
        },
      }),
      [`GET /api/projects/${P}/assets`]: () => ({ json: [] }),
    });
    renderRoutes(routes, `/projects/${P}/publish?tab=cover`);
    const size = await screen.findByRole("region", { name: "Size from the final page count" });
    await waitFor(() => expect(within(size).getByText("0.2702 in")).toBeInTheDocument());
    expect(within(size).getByText(/12.5202 × 9.2500 in/)).toBeInTheDocument();
    expect(within(size).getByRole("alert")).toHaveTextContent("built for 96 pages");
  });
});
