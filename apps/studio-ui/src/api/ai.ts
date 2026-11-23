import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, call, type Schemas } from "./client";
import { keys as baseKeys } from "./hooks";

export type AiStatus = Schemas["AiStatusOut"];
export type Provider = Schemas["ProviderOut"];
export type ProviderKind = Schemas["ProviderKindOut"];
export type ModelInfo = Schemas["ModelOut"];
export type Health = Schemas["HealthOut"];
export type Route = Schemas["RouteOut"];
export type Price = Schemas["PriceOut"];
export type PriceIn = Schemas["PriceIn"];
export type Consent = Schemas["ConsentOut"];
export type AiRequest = Schemas["AiRequestIn"];
export type Estimate = Schemas["EstimateOut"];
export type Job = Schemas["JobOut"];
export type JobLog = Schemas["JobLogOut"];
export type Proposal = Schemas["ProposalOut"];
export type Usage = Schemas["UsageOut"];
export type AiTask = Job["task"];
export type ProposalMode = Proposal["mode"];

export const TASKS: { value: AiTask; label: string; help: string }[] = [
  { value: "draft", label: "Draft", help: "Write new text that continues the chapter." },
  { value: "revise", label: "Revise", help: "Rewrite the selected passage." },
  { value: "translate", label: "Translate", help: "Translate the selection or the chapter." },
  { value: "summarize", label: "Summarize", help: "A summary for your notes." },
  { value: "brainstorm", label: "Brainstorm", help: "A list of ideas for your notes." },
  { value: "outline", label: "Outline", help: "An outline for your notes." },
  { value: "research", label: "Research", help: "Questions and directions for your notes (no web access)." },
];

export const STAGES: Record<string, string> = {
  queued: "Waiting to start",
  preparing: "Preparing the request",
  calling_model: "Waiting for the model",
  receiving: "Receiving text",
  waiting_to_retry: "Waiting to retry",
  cancelling: "Cancelling",
  ready_for_review: "Ready for review",
  cancelled: "Cancelled",
  failed: "Failed",
  interrupted: "Interrupted",
};

export const ACTIVE: Job["status"][] = ["queued", "running"];

export const aiKeys = {
  status: ["ai", "status"] as const,
  kinds: ["ai", "kinds"] as const,
  providers: ["ai", "providers"] as const,
  routes: ["ai", "routes"] as const,
  prices: (pid: string) => ["ai", "prices", pid] as const,
  consent: (projectId: string) => ["ai", "consent", projectId] as const,
  jobs: (filter: Record<string, string | undefined>) => ["ai", "jobs", filter] as const,
  logs: (id: string) => ["ai", "logs", id] as const,
  proposals: (projectId: string, chapterId?: string) =>
    ["ai", "proposals", projectId, chapterId ?? "all"] as const,
  usage: (projectId?: string) => ["ai", "usage", projectId ?? "all"] as const,
};

function useInvalidateAi() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["ai"] });
    void qc.invalidateQueries({ queryKey: baseKeys.system });
    void qc.invalidateQueries({ queryKey: ["activity"] });
  };
}

export function useAiStatus(enabled = true, poll = false) {
  return useQuery<AiStatus>({
    queryKey: aiKeys.status,
    queryFn: () => call(api.GET("/api/ai/status")),
    enabled,
    refetchInterval: poll ? 2000 : false,
  });
}

export function useSetPrivacy() {
  const invalidate = useInvalidateAi();
  return useMutation({
    mutationFn: (body: Schemas["PrivacyIn"]) => call(api.PUT("/api/ai/privacy", { body })),
    onSuccess: invalidate,
  });
}

export function useProviderKinds() {
  return useQuery<ProviderKind[]>({
    queryKey: aiKeys.kinds,
    queryFn: () => call(api.GET("/api/ai/provider-kinds")),
    staleTime: Infinity,
  });
}

export function useProviders(enabled = true) {
  return useQuery<Provider[]>({
    queryKey: aiKeys.providers,
    queryFn: () => call(api.GET("/api/ai/providers")),
    enabled,
  });
}

const pp = (id: string) => ({ params: { path: { provider_id: id } } });

export function useProviderActions() {
  const invalidate = useInvalidateAi();
  const opts = { onSuccess: invalidate };
  return {
    create: useMutation({
      mutationFn: (body: Schemas["ProviderCreate"]) => call(api.POST("/api/ai/providers", { body })),
      ...opts,
    }),
    update: useMutation({
      mutationFn: ({ id, ...body }: Schemas["ProviderPatch"] & { id: string }) =>
        call(api.PATCH("/api/ai/providers/{provider_id}", { ...pp(id), body })),
      ...opts,
    }),
    remove: useMutation({
      mutationFn: (id: string) => call(api.DELETE("/api/ai/providers/{provider_id}", pp(id))),
      ...opts,
    }),
    setKey: useMutation({
      mutationFn: ({ id, api_key }: { id: string; api_key: string }) =>
        call(api.PUT("/api/ai/providers/{provider_id}/key", { ...pp(id), body: { api_key } })),
      ...opts,
    }),
    deleteKey: useMutation({
      mutationFn: (id: string) => call(api.DELETE("/api/ai/providers/{provider_id}/key", pp(id))),
      ...opts,
    }),
    test: useMutation({
      mutationFn: (id: string) => call(api.POST("/api/ai/providers/{provider_id}/test", pp(id))),
      ...opts,
    }),
    refresh: useMutation({
      mutationFn: (id: string) => call(api.POST("/api/ai/providers/{provider_id}/models/refresh", pp(id))),
      ...opts,
    }),
    putModel: useMutation({
      mutationFn: ({ id, ...body }: Schemas["ManualModelIn"] & { id: string }) =>
        call(api.PUT("/api/ai/providers/{provider_id}/models", { ...pp(id), body })),
      ...opts,
    }),
  };
}

export function useRoutes(enabled = true) {
  return useQuery<Route[]>({
    queryKey: aiKeys.routes,
    queryFn: () => call(api.GET("/api/ai/routes")),
    enabled,
  });
}

export function useRouteActions() {
  const invalidate = useInvalidateAi();
  return {
    put: useMutation({
      mutationFn: ({ task, ...body }: Schemas["RouteIn"] & { task: AiTask }) =>
        call(api.PUT("/api/ai/routes/{task}", { params: { path: { task } }, body })),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (task: AiTask) => call(api.DELETE("/api/ai/routes/{task}", { params: { path: { task } } })),
      onSuccess: invalidate,
    }),
  };
}

export function usePrices(providerId: string) {
  return useQuery<Price[]>({
    queryKey: aiKeys.prices(providerId),
    queryFn: () => call(api.GET("/api/ai/providers/{provider_id}/prices", pp(providerId))),
  });
}

export function usePriceActions(providerId: string) {
  const invalidate = useInvalidateAi();
  return {
    put: useMutation({
      mutationFn: (body: PriceIn) =>
        call(api.PUT("/api/ai/providers/{provider_id}/prices", { ...pp(providerId), body })),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (priceId: string) =>
        call(
          api.DELETE("/api/ai/providers/{provider_id}/prices/{price_id}", {
            params: { path: { provider_id: providerId, price_id: priceId } },
          }),
        ),
      onSuccess: invalidate,
    }),
  };
}

export function useConsent(projectId: string, enabled = true) {
  return useQuery<Consent[]>({
    queryKey: aiKeys.consent(projectId),
    queryFn: () =>
      call(api.GET("/api/projects/{project_id}/ai/consent", { params: { path: { project_id: projectId } } })),
    enabled,
  });
}

export function useConsentActions(projectId: string) {
  const invalidate = useInvalidateAi();
  const path = (provider_id: string) => ({ params: { path: { project_id: projectId, provider_id } } });
  return {
    grant: useMutation({
      mutationFn: (providerId: string) =>
        call(api.PUT("/api/projects/{project_id}/ai/consent/{provider_id}", path(providerId))),
      onSuccess: invalidate,
    }),
    revoke: useMutation({
      mutationFn: (providerId: string) =>
        call(api.DELETE("/api/projects/{project_id}/ai/consent/{provider_id}", path(providerId))),
      onSuccess: invalidate,
    }),
  };
}

export function useEstimate(projectId: string) {
  return useMutation({
    mutationFn: (body: AiRequest) =>
      call(
        api.POST("/api/projects/{project_id}/ai/estimate", {
          params: { path: { project_id: projectId } },
          body,
        }),
      ),
  });
}

export function useEnqueue(projectId: string) {
  const invalidate = useInvalidateAi();
  return useMutation({
    mutationFn: (body: AiRequest) =>
      call(
        api.POST("/api/projects/{project_id}/ai/jobs", { params: { path: { project_id: projectId } }, body }),
      ),
    onSuccess: invalidate,
  });
}

/** Jobs, polled once a second while any of them is still queued or running. */
export function useJobs(
  filter: { project_id?: string; chapter_id?: string; status?: Job["status"] },
  enabled = true,
) {
  return useQuery<Job[]>({
    queryKey: aiKeys.jobs(filter),
    queryFn: () => call(api.GET("/api/ai/jobs", { params: { query: { ...filter, limit: 200 } } })),
    enabled,
    refetchInterval: (q) => ((q.state.data ?? []).some((j) => ACTIVE.includes(j.status)) ? 1000 : false),
  });
}

export function useJobLogs(jobId: string, active: boolean) {
  return useQuery<JobLog[]>({
    queryKey: aiKeys.logs(jobId),
    queryFn: () => call(api.GET("/api/ai/jobs/{job_id}/logs", { params: { path: { job_id: jobId } } })),
    refetchInterval: active ? 1000 : false,
  });
}

export function useJobActions() {
  const invalidate = useInvalidateAi();
  const path = (job_id: string) => ({ params: { path: { job_id } } });
  return {
    cancel: useMutation({
      mutationFn: (id: string) => call(api.POST("/api/ai/jobs/{job_id}/cancel", path(id))),
      onSuccess: invalidate,
    }),
    retry: useMutation({
      mutationFn: (id: string) => call(api.POST("/api/ai/jobs/{job_id}/retry", path(id))),
      onSuccess: invalidate,
    }),
  };
}

export function useProposals(projectId: string, chapterId?: string, enabled = true) {
  return useQuery<Proposal[]>({
    queryKey: aiKeys.proposals(projectId, chapterId),
    queryFn: () =>
      call(
        api.GET("/api/projects/{project_id}/proposals", {
          params: { path: { project_id: projectId }, query: { chapter_id: chapterId, status: "pending" } },
        }),
      ),
    enabled,
  });
}

export function useProposalActions(projectId: string, chapterId: string) {
  const qc = useQueryClient();
  const invalidate = useInvalidateAi();
  const path = (proposal_id: string) => ({ params: { path: { project_id: projectId, proposal_id } } });
  return {
    accept: useMutation({
      mutationFn: ({ id, ...body }: Schemas["AcceptIn"] & { id: string }) =>
        call(api.POST("/api/projects/{project_id}/proposals/{proposal_id}/accept", { ...path(id), body })),
      onSuccess: (res) => {
        qc.setQueryData(baseKeys.content(projectId, chapterId), res.save.content);
        void qc.invalidateQueries({ queryKey: ["revisions"] });
        void qc.invalidateQueries({ queryKey: baseKeys.chapters(projectId) });
        invalidate();
      },
    }),
    reject: useMutation({
      mutationFn: (id: string) =>
        call(api.POST("/api/projects/{project_id}/proposals/{proposal_id}/reject", path(id))),
      onSuccess: invalidate,
    }),
  };
}

export function useUsage(projectId?: string) {
  return useQuery<Usage>({
    queryKey: aiKeys.usage(projectId),
    queryFn: () => call(api.GET("/api/ai/usage", { params: { query: { project_id: projectId } } })),
  });
}

/** "On this computer" or "Cloud: text goes to X". Shown wherever a model is chosen. */
export function whereLabel(local: boolean, label: string | null | undefined): string {
  return local ? "On this computer" : `Cloud: your text is sent to ${label ?? "the provider"}`;
}

export function capabilityLabel(value: string | undefined): string {
  if (!value || value === "unknown") return "Unknown";
  const [source, flag] = value.split(":");
  const yes = flag === "true" ? "Yes" : "No";
  const by =
    source === "reported"
      ? "reported by the provider"
      : source === "documented"
        ? "per the provider's docs"
        : "set by you";
  return `${yes} (${by})`;
}

export function newRequestId(): string {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}
