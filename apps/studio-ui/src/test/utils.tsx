import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import axe from "axe-core";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router";
import { vi } from "vitest";
import { AnnouncerProvider } from "../components/Announcer";
import type { Project } from "../api/client";

export type Handler = (req: { method: string; url: URL; body: unknown }) => {
  status?: number;
  json?: unknown;
};

/** Route fetch calls to handlers keyed by "METHOD /path". Unmatched calls fail the test loudly. */
export function mockApi(handlers: Record<string, Handler>) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(String(input), init);
    const url = new URL(req.url);
    const text = req.method === "GET" ? "" : await req.text();
    const body = text ? JSON.parse(text) : undefined;
    calls.push({ method: req.method, path: url.pathname, body });
    const key = `${req.method} ${url.pathname}`;
    const handler = handlers[key];
    if (!handler) throw new Error(`Unhandled API call in test: ${key}`);
    const res = handler({ method: req.method, url, body });
    const status = res.status ?? 200;
    const isProblem = status >= 400;
    return new Response(status === 204 ? null : JSON.stringify(res.json ?? null), {
      status,
      headers: { "content-type": isProblem ? "application/problem+json" : "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export function renderRoutes(routes: RouteObject[], initialPath: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [initialPath] });
  const utils = render(
    <QueryClientProvider client={qc}>
      <AnnouncerProvider>
        <RouterProvider router={router} />
      </AnnouncerProvider>
    </QueryClientProvider>,
  );
  return { ...utils, router };
}

export async function axeViolations(container: Element) {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } }, // jsdom has no layout/colors; contrast is checked in Playwright
  });
  return results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

export function project(overrides: Partial<Project> = {}): Project {
  return {
    id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
    title: "The Quiet Engine",
    subtitle: null,
    author_name: null,
    project_type: "technical",
    language: "en",
    audience: null,
    target_word_count: 30000,
    publication_formats: ["ebook"],
    status: "active",
    is_demo: false,
    duplicated_from_id: null,
    created_at: "2026-11-22T10:00:00.000Z",
    updated_at: "2026-11-22T10:00:00.000Z",
    archived_at: null,
    chapter_count: 2,
    word_count: 1200,
    ...overrides,
  };
}

export const systemInfo = {
  app_version: "0.1.0",
  schema_revision: "0002",
  workspace_path: "C:/ws",
  privacy_mode: "local_only",
  env: "test",
};
