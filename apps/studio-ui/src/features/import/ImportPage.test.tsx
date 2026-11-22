import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { routes } from "../../app/routes";
import { axeViolations, mockApi, project, renderRoutes, systemInfo } from "../../test/utils";

const NEW = "01ARZ3NDEKTSV4RRFFQ69G5FB0";

function preview(extra = {}) {
  return {
    id: "01ARZ3NDEKTSV4RRFFQ69G5FC0",
    status: "preview_ready",
    importer: "html",
    original_name: "book.html",
    sha256: "a".repeat(64),
    byte_size: 1000,
    lossy: true,
    target_project_id: null,
    project_id: null,
    suggested_title: "The Quiet Engine",
    chapters: [
      {
        index: 0,
        title: "One",
        word_count: 30,
        block_count: 3,
        image_count: 1,
        preview_source: "Text one",
        duplicate_of_chapter_id: null,
        duplicate_reason: null,
      },
      {
        index: 1,
        title: "Two",
        word_count: 20,
        block_count: 2,
        image_count: 0,
        preview_source: "Text two",
        duplicate_of_chapter_id: "X",
        duplicate_reason: "same title as an existing chapter",
      },
    ],
    warnings: [
      { code: "removed_elements", message: "Removed unsafe or unsupported embedded content: script ×1." },
    ],
    previously_imported_at: null,
    created_at: "2026-11-22T10:00:00.000Z",
    ...extra,
  };
}

describe("Import page", () => {
  it("previews detected chapters with warnings and duplicates, then commits the chosen ones", async () => {
    const { calls } = mockApi({
      "GET /api/system/info": () => ({ json: systemInfo }),
      "GET /api/projects": () => ({ json: { items: [project()], total: 1 } }),
      "POST /api/imports": () => ({ status: 201, json: preview() }),
      [`POST /api/imports/${preview().id}/commit`]: () => ({
        json: { project_id: NEW, chapter_ids: ["c1"], import_run: preview({ status: "committed" }) },
      }),
      [`GET /api/projects/${NEW}`]: () => ({ json: project({ id: NEW }) }),
      [`GET /api/projects/${NEW}/chapters`]: () => ({ json: [] }),
      [`GET /api/projects/${NEW}/exports`]: () => ({ json: [] }),
      [`GET /api/projects/${NEW}/backups`]: () => ({ json: [] }),
      "GET /api/activity": () => ({ json: [] }),
    });
    const { container, router } = renderRoutes(routes, "/import");
    const user = userEvent.setup();
    expect(await axeViolations(container)).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Show what will be imported" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a file");

    await user.upload(
      screen.getByLabelText("File"),
      new File(["<h1>One</h1>"], "book.html", { type: "text/html" }),
    );
    await user.click(screen.getByRole("button", { name: "Show what will be imported" }));
    expect(await screen.findByText(/2 chapters detected/)).toBeInTheDocument();
    expect(screen.getByText(/Removed unsafe or unsupported/)).toBeInTheDocument();
    expect(screen.getByText(/Possible duplicate: same title/)).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Two" }));
    await user.clear(screen.getByLabelText("New book title"));
    await user.type(screen.getByLabelText("New book title"), "My Import");
    await user.click(screen.getByRole("button", { name: /Import 1 chapter/ }));
    await waitFor(() => expect(router.state.location.pathname).toBe(`/projects/${NEW}`));
    const body = calls.find((c) => c.path.endsWith("/commit"))?.body;
    expect(body).toMatchObject({ mode: "new_project", project_title: "My Import", include: [0] });
  });

  it("explains a failed import and that the original was kept", async () => {
    mockApi({
      "GET /api/system/info": () => ({ json: systemInfo }),
      "GET /api/projects": () => ({ json: { items: [], total: 0 } }),
      "POST /api/imports": () => ({
        status: 201,
        json: preview({
          status: "failed",
          chapters: [],
          warnings: [
            { code: "import_failed", message: "No text could be extracted. This looks like a scanned PDF." },
          ],
        }),
      }),
    });
    renderRoutes(routes, "/import");
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText("File"), new File(["%PDF-"], "scan.pdf"));
    await user.click(screen.getByRole("button", { name: "Show what will be imported" }));
    expect(await screen.findByText(/scanned PDF/)).toBeInTheDocument();
    expect(screen.getByText(/The uploaded file was kept unchanged/)).toBeInTheDocument();
  });
});
