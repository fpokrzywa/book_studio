import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { routes } from "../../app/routes";
import { axeViolations, mockApi, project, renderRoutes, systemInfo } from "../../test/utils";

const common = {
  "GET /api/system/info": () => ({ json: systemInfo }),
  "GET /api/activity": () => ({ json: [] }),
};

describe("LibraryPage", () => {
  it("shows an inviting empty state when there are no books", async () => {
    mockApi({ ...common, "GET /api/projects": () => ({ json: { items: [], total: 0 } }) });
    const { container } = renderRoutes(routes, "/");
    expect(await screen.findByRole("heading", { name: "No books yet" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start your first book" })).toHaveAttribute("href", "/new");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("renders real projects from the API as volumes with progress", async () => {
    mockApi({
      ...common,
      "GET /api/projects": () => ({
        json: {
          items: [project(), project({ id: "01ARZ3NDEKTSV4RRFFQ69G5FAW", title: "Second", is_demo: true })],
          total: 2,
        },
      }),
    });
    const { container } = renderRoutes(routes, "/");
    const link = await screen.findByRole("link", { name: "The Quiet Engine" });
    expect(link).toHaveAttribute("href", "/projects/01ARZ3NDEKTSV4RRFFQ69G5FAV");
    expect(screen.getByText("2 books")).toBeInTheDocument();
    expect(screen.getAllByText("1,200 of 30,000 words (4%)")).toHaveLength(2);
    expect(screen.getByText("Demo")).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("sends search, filter and sort choices to the API", async () => {
    const { calls } = mockApi({ ...common, "GET /api/projects": () => ({ json: { items: [], total: 0 } }) });
    renderRoutes(routes, "/");
    const user = userEvent.setup();
    await screen.findByRole("heading", { name: "No books yet" });
    await user.selectOptions(screen.getByLabelText("Kind of book"), "memoir");
    await user.selectOptions(screen.getByLabelText("Sort by"), "target_word_count");
    await user.type(screen.getByLabelText("Search books"), "engine");
    await waitFor(() => {
      const last = calls.filter((c) => c.path === "/api/projects").at(-1);
      expect(last).toBeDefined();
    });
    await waitFor(() =>
      expect(
        (globalThis.fetch as unknown as { mock: { calls: [Request][] } }).mock.calls
          .map(([r]) => new URL(r.url).search)
          .some(
            (s) =>
              s.includes("q=engine") &&
              s.includes("project_type=memoir") &&
              s.includes("sort=target_word_count"),
          ),
      ).toBe(true),
    );
    expect(screen.getByRole("heading", { name: "No books match" })).toBeInTheDocument();
  });

  it("shows an actionable error when Core is unreachable, and retries", async () => {
    let fail = true;
    mockApi({
      ...common,
      "GET /api/projects": () =>
        fail ? { status: 502, json: {} } : { json: { items: [project()], total: 1 } },
    });
    renderRoutes(routes, "/");
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Can't reach Personal Book Studio Core.")).toBeInTheDocument();
    fail = false;
    await userEvent.setup().click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: "The Quiet Engine" })).toBeInTheDocument();
  });

  it("labels later-phase navigation as disabled, not as working links", async () => {
    mockApi({ ...common, "GET /api/projects": () => ({ json: { items: [], total: 0 } }) });
    renderRoutes(routes, "/");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    for (const name of ["Publishing"]) {
      expect(within(nav).queryByRole("link", { name: new RegExp(name) })).toBeNull();
      const item = within(nav).getByText(name);
      expect(item.closest("[aria-disabled='true']")).not.toBeNull();
    }
    expect(within(nav).getAllByText(/Not yet implemented/)).toHaveLength(1);
    // Phase 03 sections are real links now.
    expect(within(nav).getByRole("link", { name: "AI settings" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "AI jobs" })).toBeInTheDocument();
    // Phase 04 sections too.
    expect(within(nav).getByRole("link", { name: "Knowledge" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Author voice" })).toBeInTheDocument();
    expect(await screen.findByText("Local-only")).toBeInTheDocument();
  });
});
