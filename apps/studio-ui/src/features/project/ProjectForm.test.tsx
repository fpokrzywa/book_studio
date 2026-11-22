import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { routes } from "../../app/routes";
import { axeViolations, mockApi, project, renderRoutes, systemInfo } from "../../test/utils";
import { initialValues, toPayload, validate } from "./ProjectForm";

describe("ProjectForm validation", () => {
  it("requires a title and a sensible language and target", () => {
    const v = { ...initialValues(), title: "  ", language: "english", target_word_count: "-3" };
    const errors = validate(v);
    expect(Object.keys(errors).sort()).toEqual(["language", "target_word_count", "title"]);
    expect(
      validate({ ...initialValues(), title: "Ok", target_word_count: "1.5" }).target_word_count,
    ).toBeDefined();
    expect(validate({ ...initialValues(), title: "Ok", language: "en-GB", target_word_count: "" })).toEqual(
      {},
    );
  });

  it("builds a clean payload", () => {
    const payload = toPayload({
      ...initialValues(),
      title: "  A Book ",
      subtitle: " ",
      target_word_count: "40000",
      publication_formats: ["ebook", "paperback"],
    });
    expect(payload).toMatchObject({ title: "A Book", subtitle: null, target_word_count: 40000 });
  });
});

describe("New book page", () => {
  it("blocks submission with an announced, linked error, then creates the book", async () => {
    const { calls } = mockApi({
      "GET /api/system/info": () => ({ json: systemInfo }),
      "POST /api/projects": ({ body }) => ({
        status: 201,
        json: project({ title: (body as { title: string }).title }),
      }),
      "GET /api/projects/01ARZ3NDEKTSV4RRFFQ69G5FAV": () => ({ json: project() }),
      "GET /api/projects/01ARZ3NDEKTSV4RRFFQ69G5FAV/chapters": () => ({ json: [] }),
      "GET /api/projects/01ARZ3NDEKTSV4RRFFQ69G5FAV/exports": () => ({ json: [] }),
      "GET /api/activity": () => ({ json: [] }),
    });
    const { container, router } = renderRoutes(routes, "/new");
    const user = userEvent.setup();
    expect(await axeViolations(container)).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Create book" }));
    const title = screen.getByLabelText("Title");
    expect(title).toHaveAttribute("aria-invalid", "true");
    expect(title).toHaveAccessibleDescription(/working title/);
    expect(title).toHaveFocus();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);

    await user.type(title, "The Quiet Engine");
    await user.selectOptions(screen.getByLabelText("Kind of book"), "technical");
    await user.click(screen.getByLabelText("Paperback"));
    await user.click(screen.getByRole("button", { name: "Create book" }));

    await screen.findByRole("heading", { name: "The Quiet Engine", level: 1 });
    expect(router.state.location.pathname).toBe("/projects/01ARZ3NDEKTSV4RRFFQ69G5FAV");
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toMatchObject({
      title: "The Quiet Engine",
      project_type: "technical",
      publication_formats: ["ebook", "paperback"],
    });
  });
});
