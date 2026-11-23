import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AuthState } from "../../api/auth";
import { api, call, runTask, setCsrfToken } from "../../api/client";
import { AnnouncerProvider } from "../../components/Announcer";
import { axeViolations, mockApi } from "../../test/utils";
import { AuthGate } from "./AuthGate";

const signedOut: AuthState = {
  setup_required: false,
  signed_in: false,
  username: null,
  csrf_token: null,
  session_expires_at: null,
  deployment: "server",
  password_min_length: 12,
};
const signedIn: AuthState = { ...signedOut, signed_in: true, username: "author", csrf_token: "csrf-abc" };

function renderGate() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AnnouncerProvider>
        <AuthGate>
          <p>The studio</p>
        </AuthGate>
      </AnnouncerProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  setCsrfToken(null);
  vi.unstubAllGlobals();
});

describe("AuthGate", () => {
  it("shows nothing of the studio until signed in, then signs in", async () => {
    let state: AuthState = signedOut;
    const { calls, fetchMock } = mockApi({
      "GET /api/auth/state": () => ({ json: state }),
      "POST /api/auth/login": ({ body }) => {
        const b = body as { username: string; password: string };
        if (b.password !== "right password here") {
          return {
            status: 401,
            json: { title: "That username and password do not match.", code: "not_signed_in" },
          };
        }
        state = signedIn;
        return { json: signedIn };
      },
    });
    const { container } = renderGate();
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByText("The studio")).not.toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);

    await userEvent.type(screen.getByLabelText("Username"), "author");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("That username and password do not match.")).toBeInTheDocument();

    await userEvent.clear(screen.getByLabelText("Password"));
    await userEvent.type(screen.getByLabelText("Password"), "right password here");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("The studio")).toBeInTheDocument();
    const login = fetchMock.mock.calls.find(([r]) => (r as Request).url.endsWith("/api/auth/login"));
    expect((login?.[0] as Request).headers.get("X-PBS-CSRF")).toBeTruthy(); // anti-forgery header on sign-in
    expect(calls.filter((c) => c.path === "/api/auth/login")).toHaveLength(2);
  });

  it("asks for the setup code when the studio has no account", async () => {
    mockApi({ "GET /api/auth/state": () => ({ json: { ...signedOut, setup_required: true } }) });
    const { container } = renderGate();
    expect(await screen.findByRole("heading", { name: "Create your studio account" })).toBeInTheDocument();
    expect(screen.getByLabelText("Setup code")).toBeRequired();
    await userEvent.type(screen.getByLabelText("Password"), "one long password");
    await userEvent.type(screen.getByLabelText("Repeat the password"), "another one");
    expect(screen.getByText("The two passwords are different.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create account" })).toBeDisabled();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("returns to sign-in when Core says the session ended", async () => {
    let state: AuthState = signedIn;
    mockApi({
      "GET /api/auth/state": () => ({ json: state }),
      "GET /api/projects": () => ({
        status: 401,
        json: { title: "Sign in to continue.", code: "not_signed_in" },
      }),
    });
    renderGate();
    expect(await screen.findByText("The studio")).toBeInTheDocument();
    state = signedOut;
    await call(api.GET("/api/projects", { params: { query: {} } })).catch(() => undefined);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });
});

describe("API client", () => {
  it("sends the session's CSRF token on writes only", async () => {
    const { fetchMock } = mockApi({
      "GET /api/projects": () => ({ json: { items: [], total: 0 } }),
      "POST /api/projects": () => ({ status: 201, json: {} }),
    });
    setCsrfToken("csrf-xyz");
    await call(api.GET("/api/projects", { params: { query: {} } }));
    await call(api.POST("/api/projects", { body: { title: "t", project_type: "fiction" } as never }));
    const [get, post] = fetchMock.mock.calls.map(([r]) => r as Request);
    expect(get?.headers.get("X-PBS-CSRF")).toBeNull();
    expect(post?.headers.get("X-PBS-CSRF")).toBe("csrf-xyz");
  });

  it("waits for a background task and returns its result or its problem", async () => {
    let polls = 0;
    mockApi({
      "GET /api/tasks/t1": () => ({
        json: { id: "t1", status: ++polls < 2 ? "running" : "succeeded", result: { ok: 1 }, attempt: 1 },
      }),
      "GET /api/tasks/t2": () => ({
        json: {
          id: "t2",
          status: "failed",
          error_code: "no_chapters",
          error_message: "Nothing to build.",
          attempt: 1,
        },
      }),
    });
    const queued = (id: string) =>
      Promise.resolve({ id, kind: "publishing.build", status: "queued", attempt: 0 } as never);
    await expect(runTask(queued("t1"), 1)).resolves.toEqual({ ok: 1 });
    await expect(runTask(queued("t2"), 1)).rejects.toMatchObject({
      code: "no_chapters",
      message: "Nothing to build.",
    });
    await waitFor(() => expect(polls).toBe(2));
  });
});
