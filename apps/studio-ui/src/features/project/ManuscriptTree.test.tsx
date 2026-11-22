import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { routes } from "../../app/routes";
import { axeViolations, mockApi, project, renderRoutes, systemInfo } from "../../test/utils";

const P = "01ARZ3NDEKTSV4RRFFQ69G5FAV";

function ch(id: string, title: string, extra = {}) {
  return {
    id,
    project_id: P,
    parent_id: null,
    depth: 0,
    kind: "chapter",
    position: id,
    title,
    slug: title.toLowerCase(),
    status: "draft",
    locked: false,
    target_word_count: null,
    head_revision_id: null,
    head_revision_no: 0,
    word_count: 0,
    created_at: "2026-11-22T10:00:00.000Z",
    updated_at: "2026-11-22T10:00:00.000Z",
    ...extra,
  };
}

const A = "01ARZ3NDEKTSV4RRFFQ69G5FA1";
const B = "01ARZ3NDEKTSV4RRFFQ69G5FA2";
const S = "01ARZ3NDEKTSV4RRFFQ69G5FA3";

function setup() {
  return mockApi({
    "GET /api/system/info": () => ({ json: systemInfo }),
    [`GET /api/projects/${P}`]: () => ({ json: project() }),
    [`GET /api/projects/${P}/chapters`]: () => ({
      json: [
        ch(A, "Alpha", { word_count: 500, target_word_count: 1000 }),
        ch(S, "Inner", { parent_id: A, depth: 1, kind: "section" }),
        ch(B, "Beta"),
      ],
    }),
    [`POST /api/projects/${P}/chapters/${B}/move`]: () => ({ json: [] }),
    [`POST /api/projects/${P}/chapters/${S}/move`]: () => ({ json: [] }),
    [`GET /api/projects/${P}/exports`]: () => ({ json: [] }),
    [`GET /api/projects/${P}/backups`]: () => ({ json: [] }),
    "GET /api/activity": () => ({ json: [] }),
  });
}

describe("Manuscript tree", () => {
  it("shows the canonical order with nesting, progress and keyboard-operable arrange buttons", async () => {
    const { calls } = setup();
    const { container } = renderRoutes(routes, `/projects/${P}`);
    const user = userEvent.setup();
    await screen.findByRole("link", { name: "Beta" });
    const links = screen
      .getAllByRole("link")
      .filter((l) => ["Alpha", "Inner", "Beta"].includes(l.textContent ?? ""));
    expect(links.map((l) => l.textContent)).toEqual(["Alpha", "Inner", "Beta"]);
    expect(screen.getByRole("img", { name: "50% of target length" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Move Alpha up" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Outdent Alpha" })).toBeDisabled();
    expect(await axeViolations(container)).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Move Beta up" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith(`${B}/move`))).toBe(true));
    expect(calls.find((c) => c.path.endsWith(`${B}/move`))?.body).toEqual({ parent_id: null, index: 0 });

    await user.click(screen.getByRole("button", { name: "Outdent Inner" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith(`${S}/move`))).toBe(true));
    expect(calls.find((c) => c.path.endsWith(`${S}/move`))?.body).toEqual({ parent_id: null, index: 1 });
  });

  it("validates chapter details before saving", async () => {
    setup();
    renderRoutes(routes, `/projects/${P}`);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edit details of Beta" }));
    const slug = await screen.findByLabelText("Slug");
    await user.clear(slug);
    await user.type(slug, "Not A Slug");
    await user.click(screen.getByRole("button", { name: "Save details" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/lowercase letters/);
  });
});
