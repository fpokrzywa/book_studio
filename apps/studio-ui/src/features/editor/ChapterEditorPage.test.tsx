import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { routes } from "../../app/routes";
import { axeViolations, mockApi, project, renderRoutes, systemInfo, type Handler } from "../../test/utils";

vi.mock("./SourceEditor", async () => {
  const fake = await import("../../test/fakeSourceEditor");
  return { SourceEditor: fake.FakeSourceEditor };
});

const P = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
const C = "01ARZ3NDEKTSV4RRFFQ69G5FAX";
const base = `/api/projects/${P}/chapters/${C}`;

function chapter(overrides = {}) {
  return {
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
    head_revision_id: null,
    head_revision_no: 1,
    word_count: 2,
    created_at: "2026-11-22T10:00:00.000Z",
    updated_at: "2026-11-22T10:00:00.000Z",
    ...overrides,
  };
}

function content(revision_no: number, source_md: string, draft: unknown = null) {
  return {
    chapter_id: C,
    revision_id: `R${revision_no}`,
    revision_no,
    source_md,
    word_count: 2,
    saved_at: "2026-11-22T10:00:00.000Z",
    draft,
  };
}

function revision(no: number, extra = {}) {
  return {
    id: `R${no}`,
    revision_no: no,
    origin: "human",
    word_count: 2,
    content_hash: "h",
    parser_version: "bookmd-1.0",
    label: null,
    note: null,
    restored_from_revision_no: null,
    is_head: false,
    created_at: "2026-11-22T10:00:00.000Z",
    ...extra,
  };
}

function setup(overrides: Record<string, Handler> = {}, initial = content(1, "Old text.")) {
  return mockApi({
    "GET /api/system/info": () => ({ json: systemInfo }),
    [`GET /api/projects/${P}`]: () => ({ json: project() }),
    [`GET ${base}`]: () => ({ json: chapter() }),
    [`GET ${base}/content`]: () => ({ json: initial }),
    [`GET /api/projects/${P}/chapters`]: () => ({ json: [chapter()] }),
    [`PUT ${base}/draft`]: ({ body }) => ({
      json: content(1, "Old text.", { ...(body as object), updated_at: "2026-11-22T10:01:00.000Z" }),
    }),
    [`POST /api/projects/${P}/preview`]: () => ({
      json: { html: "<p>Preview</p>", word_count: 2, warnings: [], citation_keys: [], block_count: 1 },
    }),
    [`GET /api/projects/${P}/exports`]: () => ({ json: [] }),
    [`GET /api/projects/${P}/backups`]: () => ({ json: [] }),
    "GET /api/projects": () => ({ json: { items: [], total: 0 } }),
    "GET /api/activity": () => ({ json: [] }),
    [`GET /api/projects/${P}/proposals`]: () => ({ json: [] }),
    ...overrides,
  });
}

beforeEach(() => {
  localStorage.setItem("pbs.editor.view", "write");
});

describe("Chapter editor", () => {
  it("tracks unsaved changes and saves with Ctrl+S using the expected revision", async () => {
    const { calls } = setup({
      [`PUT ${base}/content`]: ({ body }) => ({
        json: { created: true, content: content(2, (body as { source_md: string }).source_md) },
      }),
    });
    const { container } = renderRoutes(routes, `/projects/${P}/chapters/${C}`);
    const user = userEvent.setup();
    const box = await screen.findByLabelText("Chapter text (Markdown)");
    expect(box).toHaveValue("Old text.");
    expect(screen.getByText(/Saved as revision 1/)).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);

    await user.type(box, " More.");
    expect(screen.getByText(/Unsaved changes/)).toBeInTheDocument();
    await user.keyboard("{Control>}s{/Control}");

    await waitFor(() => expect(screen.getByText(/Saved as revision 2/)).toBeInTheDocument());
    const put = calls.find((c) => c.method === "PUT" && c.path.endsWith("/content"));
    expect(put?.body).toEqual({ source_md: "Old text. More.", expected_head_no: 1 });
  });

  it("autosaves a draft (not a revision) after typing stops", async () => {
    const { calls } = setup();
    renderRoutes(routes, `/projects/${P}/chapters/${C}`);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Chapter text (Markdown)"), "!");
    await waitFor(
      () => expect(calls.some((c) => c.method === "PUT" && c.path.endsWith("/draft"))).toBe(true),
      {
        timeout: 4000,
      },
    );
    const draft = calls.find((c) => c.path.endsWith("/draft"));
    expect(draft?.body).toEqual({ source_md: "Old text.!", base_revision_no: 1 });
    expect(calls.some((c) => c.method === "PUT" && c.path.endsWith("/content"))).toBe(false);
    await waitFor(() => expect(screen.getByText(/Draft autosaved/)).toBeInTheDocument());
  });

  it("recovers an autosaved draft after a reload and can discard it", async () => {
    setup(
      {
        [`DELETE ${base}/draft`]: () => ({ json: content(1, "Old text.") }),
      },
      content(1, "Old text.", {
        source_md: "Recovered words",
        base_revision_no: 1,
        updated_at: "2026-11-22T10:05:00.000Z",
      }),
    );
    renderRoutes(routes, `/projects/${P}/chapters/${C}`);
    const user = userEvent.setup();
    expect(await screen.findByLabelText("Chapter text (Markdown)")).toHaveValue("Recovered words");
    expect(screen.getByText(/Recovered unsaved changes/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    await waitFor(() => expect(screen.getByLabelText("Chapter text (Markdown)")).toHaveValue("Old text."));
  });

  it("offers a clear choice when the chapter was saved elsewhere (409)", async () => {
    let attempt = 0;
    const { calls } = setup({
      [`PUT ${base}/content`]: ({ body }) => {
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
      },
    });
    renderRoutes(routes, `/projects/${P}/chapters/${C}`);
    const user = userEvent.setup();
    const box = await screen.findByLabelText("Chapter text (Markdown)");
    await user.type(box, " Mine.");
    await user.click(screen.getByRole("button", { name: "Save" }));

    const dialog = await screen.findByRole("alertdialog", { name: "This chapter changed somewhere else" });
    expect(dialog).toHaveTextContent("Revision 3");
    await user.click(screen.getByRole("button", { name: "Save my text as the newest revision" }));
    await waitFor(() => expect(screen.getByText(/Saved as revision 4/)).toBeInTheDocument());
    const puts = calls.filter((c) => c.method === "PUT" && c.path.endsWith("/content"));
    expect(puts.map((p) => (p.body as { expected_head_no: number }).expected_head_no)).toEqual([1, 3]);
  });

  it("asks before leaving while the autosave is still pending", async () => {
    setup();
    const { router } = renderRoutes(routes, `/projects/${P}/chapters/${C}`);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Chapter text (Markdown)"), "!");
    await act(() => router.navigate("/"));
    expect(
      await screen.findByRole("alertdialog", { name: "Leave before the autosave finishes?" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Stay on this chapter" }));
    expect(router.state.location.pathname).toBe(`/projects/${P}/chapters/${C}`);
  });

  it("shows history, compares two revisions and restores as a new revision", async () => {
    const { calls } = setup({
      [`GET ${base}/revisions`]: () => ({
        json: [revision(2, { is_head: true, label: "Second pass" }), revision(1, { origin: "imported" })],
      }),
      [`GET ${base}/compare`]: () => ({
        json: {
          from_revision_no: 1,
          to_revision_no: 2,
          added_lines: 0,
          removed_lines: 0,
          changed_lines: 1,
          rows: [
            {
              kind: "replace",
              left_no: 1,
              right_no: 1,
              left: [
                { text: "The engine is ", changed: false },
                { text: "cold", changed: true },
              ],
              right: [
                { text: "The engine is ", changed: false },
                { text: "warm", changed: true },
              ],
            },
          ],
        },
      }),
      [`POST ${base}/revisions/1/restore`]: () => ({
        json: { created: true, content: content(3, "Restored text") },
      }),
    });
    renderRoutes(routes, `/projects/${P}/chapters/${C}`);
    const user = userEvent.setup();
    await screen.findByLabelText("Chapter text (Markdown)");
    await user.click(screen.getByRole("button", { name: "History" }));
    const dialog = await screen.findByRole("dialog", { name: /History of/ });
    expect(within(dialog).getByText("Second pass")).toBeInTheDocument();
    expect(within(dialog).getByText(/^Imported/)).toBeInTheDocument();

    const radiosOlder = within(dialog).getAllByLabelText("Older");
    const radiosNewer = within(dialog).getAllByLabelText("Newer");
    await user.click(radiosOlder[1]!);
    await user.click(radiosNewer[0]!);
    expect(await within(dialog).findByText("cold")).toContainHTML("cold");
    expect(within(dialog).getByText("cold").tagName).toBe("DEL");
    expect(within(dialog).getByText("warm").tagName).toBe("INS");

    await user.click(within(dialog).getByRole("button", { name: "Restore" }));
    await user.click(await screen.findByRole("button", { name: "Restore as new revision" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/revisions/1/restore"))).toBe(true));
    expect(calls.find((c) => c.path.endsWith("/restore"))?.body).toEqual({ expected_head_no: 1, note: null });
  });
});
