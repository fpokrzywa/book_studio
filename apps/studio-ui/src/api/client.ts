import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type Project = Schemas["ProjectOut"];
export type ProjectCreate = Schemas["ProjectCreate"];
export type ProjectPatch = Schemas["ProjectPatch"];
export type Chapter = Schemas["ChapterOut"];
export type ChapterContent = Schemas["ChapterContentOut"];
export type ExportRun = Schemas["ExportOut"];
export type Activity = Schemas["ActivityOut"];
export type SystemInfo = Schemas["SystemInfoOut"];
export type Capability = Schemas["CapabilityOut"];
export type ProjectType = Project["project_type"];
export type PublicationFormat = Project["publication_formats"][number];
export type ChapterStatus = Chapter["status"];

/** RFC 9457 problem returned by Core, plus any extension members. */
export interface Problem {
  type: string;
  title: string;
  status: number;
  code: string;
  detail?: string;
  [key: string]: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly problem: Problem;

  constructor(problem: Problem) {
    super(problem.title);
    this.name = "ApiError";
    this.status = problem.status;
    this.code = problem.code;
    this.problem = problem;
  }
}

function origin(): string {
  return typeof window !== "undefined" ? window.location.origin : "http://127.0.0.1";
}

// ---------- session: CSRF token and "signed out" notifications ----------

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);
let csrfToken: string | null = null;
const signedOutListeners = new Set<() => void>();

/** Set by the sign-in gate from /api/auth/state; sent as X-PBS-CSRF on every state-changing request. */
export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

/** Called when Core answers "not signed in" (session ended elsewhere, expired, or password changed). */
export function onSignedOut(listener: () => void): () => void {
  signedOutListeners.add(listener);
  return () => signedOutListeners.delete(listener);
}

function withCsrf(request: Request): Request {
  if (!UNSAFE.has(request.method.toUpperCase())) return request;
  const headers = new Headers(request.headers);
  // Sign-in requests have no session token yet; any value proves this is not a cross-site form post.
  headers.set("X-PBS-CSRF", csrfToken ?? "sign-in");
  return new Request(request, { headers });
}

async function sessionFetch(request: Request): Promise<Response> {
  const response = await globalThis.fetch(withCsrf(request));
  if (response.status === 401 && !new URL(request.url).pathname.startsWith("/api/auth/")) {
    const body = (await response
      .clone()
      .json()
      .catch(() => ({}))) as Partial<Problem>;
    if (body.code === "not_signed_in") signedOutListeners.forEach((l) => l());
  }
  return response;
}

// Resolve fetch at call time (not import time) so tests can substitute it.
export const api = createClient<paths>({ baseUrl: origin(), fetch: (request) => sessionFetch(request) });

/** Unwrap an openapi-fetch result, turning problems and network failures into ApiError. */
export async function call<T>(
  promise: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: { data?: T; error?: unknown; response: Response };
  try {
    result = await promise;
  } catch {
    throw new ApiError({
      type: "urn:pbs:problem:core_unreachable",
      title: "Can't reach Personal Book Studio Core.",
      detail: "Check that the Core service is running (see README: Starting the app), then try again.",
      status: 0,
      code: "core_unreachable",
    });
  }
  const { data, error, response } = result;
  if (response.ok) {
    return data as T;
  }
  const body = (error ?? {}) as Partial<Problem>;
  if (response.status === 502 || response.status === 504) {
    throw new ApiError({
      type: "urn:pbs:problem:core_unreachable",
      title: "Can't reach Personal Book Studio Core.",
      detail: "Check that the Core service is running (see README: Starting the app), then try again.",
      status: response.status,
      code: "core_unreachable",
    });
  }
  throw new ApiError({
    type: body.type ?? "about:blank",
    title: body.title ?? `Request failed (${response.status}).`,
    status: response.status,
    code: body.code ?? "http_error",
    ...body,
  } as Problem);
}

/** Multipart upload (openapi-fetch's JSON client is not used for files). */
export async function upload<T>(
  path: string,
  file: File | Blob,
  name: string,
  fields: Record<string, string> = {},
): Promise<T> {
  const form = new FormData();
  form.append("file", file, name);
  for (const [k, v] of Object.entries(fields)) form.append(k, v);
  return call<T>(
    sessionFetch(new Request(new URL(path, origin()).toString(), { method: "POST", body: form })).then(
      async (response) => {
        const body = await response.json().catch(() => ({}));
        return response.ok ? { data: body as T, response } : { error: body, response };
      },
    ),
  );
}

export function errorMessage(err: unknown): { title: string; detail?: string } {
  if (err instanceof ApiError) {
    return { title: err.problem.title, detail: err.problem.detail };
  }
  return {
    title: "Something unexpected went wrong.",
    detail: err instanceof Error ? err.message : undefined,
  };
}

export type Task = Schemas["TaskOut"];

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Run long work through Core's durable background queue: enqueue, then poll the task until it
 * finishes. Resolves with the task's result (the same body the old synchronous endpoint returned)
 * or throws the task's problem as an ApiError. Leaving the page does not stop the task.
 */
export async function runTask<T>(enqueue: Promise<Task>, pollMs = 750): Promise<T> {
  let task = await enqueue;
  while (task.status === "queued" || task.status === "running") {
    await sleep(pollMs);
    task = await call(api.GET("/api/tasks/{task_id}", { params: { path: { task_id: task.id } } }));
  }
  if (task.status === "succeeded") return task.result as T;
  throw new ApiError({
    type: `urn:pbs:problem:${task.error_code ?? "task_failed"}`,
    title: task.error_message ?? "The background task did not finish.",
    status: 409,
    code: task.error_code ?? "task_failed",
  });
}
