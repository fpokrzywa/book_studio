import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { routes } from "../../app/routes";
import { axeViolations, mockApi, project, renderRoutes, systemInfo } from "../../test/utils";

const P = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
const C = "01ARZ3NDEKTSV4RRFFQ69G5FAX";
const base = `/api/projects/${P}/chapters/${C}`;

function chapter(overrides = {}) {
  return {
    id: C,
    project_id: P,
    kind: "chapter",
    position: "V",
    title: "Chapter One",
    slug: "chapter-one",
    status: "draft",
    locked: false,
    target_word_count: null,
    head_revision_id: null,
    head_revision_no: 1,
    word_count: 2,
    created_at: "2026-11-22T10:00:00.000Z",
    updated_at: "2026-11-22T10:00:00.000Z",
    ...overrides,
  };
}

function content(revision_no: number, source_md: string) {
  return {
    chapter_id: C,
    revision_id: `R${revision_no}`,
    revision_no,
    source_md,
    word_count: 2,
    saved_at: "2026-11-22T10:00:00.000Z",
  };
}

function setup(saveHandler: Parameters<typeof mockApi>[0][string]) {
  return mockApi({
    "GET /api/system/info": () => ({ json: systemInfo }),
    [`GET /api/projects/${P}`]: () => ({ json: project() }),
    [`GET ${base}`]: () => ({ json: chapter() }),
    [`GET ${base}/content`]: () => ({ json: content(1, "Old text.") }),
    [`PUT ${base}/content`]: saveHandler,
    [`GET /api/projects/${P}/chapters`]: () => ({ json: [chapter()] }),
    [`GET /api/projects/${P}/exports`]: () => ({ json: [] }),
    "GET /api/projects": () => ({ json: { items: [], total: 0 } }),
    "GET /api/activity": () => ({ json: [] }),
  });
}

describe("Chapter editor", () => {
  it("tracks unsaved changes and saves with Ctrl+S using the expected revision", async () => {
    const { calls } = setup(({ body }) => ({
      json: { created: true, content: content(2, (body as { source_md: string }).source_md) },
    }));
    const { container } = renderRoutes(routes, `/projects/${P}/chapters/${C}`);
    const user = userEvent.setup();
    const box = await screen.findByLabelText("Chapter text (Markdown)");
    expect(box).toHaveValue("Old text.");
    expect(screen.getByText(/Saved as revision 1/)).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);

    await user.type(box, " More.");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    await user.keyboard("{Control>}s{/Control}");

    await waitFor(() => expect(screen.getByText(/Saved as revision 2/)).toBeInTheDocument());
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.body).toEqual({ source_md: "Old text. More.", expected_head_no: 1 });
  });

  it("offers a clear choice when the chapter was saved elsewhere (409)", async () => {
    let attempt = 0;
    const { calls } = setup(({ body }) => {
      attempt += 1;
      if (attempt === 1) {
        return {
          status: 409,
          json: {
            type: "urn:pbs:problem:conflict",
            title: "This chapter was saved elsewhere since you opened it.",
            status: 409,
            code: "conflict",
            current: content(3, "Text from another window."),
          },
        };
      }
      return { json: { created: true, content: content(4, (body as { source_md: string }).source_md) } };
    });
    renderRoutes(routes, `/projects/${P}/chapters/${C}`);
    const user = userEvent.setup();
    const box = await screen.findByLabelText("Chapter text (Markdown)");
    await user.type(box, " Mine.");
    await user.click(screen.getByRole("button", { name: "Save" }));

    const dialog = await screen.findByRole("alertdialog", { name: "This chapter changed somewhere else" });
    expect(dialog).toHaveTextContent("revision 3");
    await user.click(screen.getByRole("button", { name: "Save my text as the newest revision" }));
    await waitFor(() => expect(screen.getByText(/Saved as revision 4/)).toBeInTheDocument());
    const puts = calls.filter((c) => c.method === "PUT");
    expect(puts.map((p) => (p.body as { expected_head_no: number }).expected_head_no)).toEqual([1, 3]);
  });

  it("asks before leaving with unsaved text", async () => {
    setup(() => ({ json: {} }));
    const { router } = renderRoutes(routes, `/projects/${P}/chapters/${C}`);
    const user = userEvent.setup();
    const box = await screen.findByLabelText("Chapter text (Markdown)");
    await user.type(box, "!");
    await act(() => router.navigate("/"));
    expect(await screen.findByRole("alertdialog", { name: "Leave without saving?" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Stay on this chapter" }));
    expect(router.state.location.pathname).toBe(`/projects/${P}/chapters/${C}`);
    expect(screen.getByLabelText("Chapter text (Markdown)")).toHaveValue("Old text.!");
  });
});
