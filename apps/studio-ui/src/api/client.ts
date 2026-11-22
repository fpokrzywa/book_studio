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

// Resolve fetch at call time (not import time) so tests can substitute it.
export const api = createClient<paths>({ baseUrl: origin(), fetch: (request) => globalThis.fetch(request) });

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

export function errorMessage(err: unknown): { title: string; detail?: string } {
  if (err instanceof ApiError) {
    return { title: err.problem.title, detail: err.problem.detail };
  }
  return {
    title: "Something unexpected went wrong.",
    detail: err instanceof Error ? err.message : undefined,
  };
}
