import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, call, type Schemas } from "./client";

export type Brief = Schemas["BriefOut"];
export type BriefIn = Schemas["BriefIn"];
export type Finding = Schemas["FindingOut"];
export type FindingIn = Schemas["FindingIn"];
export type ResearchProvider = Schemas["ResearchProviderOut"];
export type ResearchSearch = Schemas["ResearchSearchOut"];
export type Outline = Schemas["OutlineOut"];
export type PlanEstimate = Schemas["PlanEstimateOut"];
export type PlanRequest = Schemas["PlanRequestIn"];
export type Run = Schemas["RunOut"];
export type ApplyResult = Schemas["ApplyOut"];

export const pKeys = {
  brief: (pid: string) => ["planning", "brief", pid] as const,
  findings: (pid: string) => ["planning", "findings", pid] as const,
  providers: ["planning", "providers"] as const,
  outlines: (pid: string) => ["planning", "outlines", pid] as const,
  runs: (pid: string) => ["planning", "runs", pid] as const,
};

const path = (pid: string) => ({ params: { path: { project_id: pid } } });

function useInvalidate() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["planning"] });
    void qc.invalidateQueries({ queryKey: ["activity"] });
  };
}

export function useCreateBook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["NewBookIn"]) => call(api.POST("/api/books", { body })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["projects"] });
      void qc.invalidateQueries({ queryKey: ["knowledge"] });
    },
  });
}

export function useBrief(pid: string) {
  return useQuery<Brief>({
    queryKey: pKeys.brief(pid),
    queryFn: () => call(api.GET("/api/projects/{project_id}/brief", path(pid))),
  });
}

export function useBriefActions(pid: string) {
  const invalidate = useInvalidate();
  return {
    save: useMutation({
      mutationFn: (body: BriefIn) =>
        call(api.PUT("/api/projects/{project_id}/brief", { ...path(pid), body })),
      onSuccess: invalidate,
    }),
    approve: useMutation({
      mutationFn: () => call(api.POST("/api/projects/{project_id}/brief/approve", path(pid))),
      onSuccess: invalidate,
    }),
  };
}

export function useFindings(pid: string, includeArchived = false) {
  return useQuery<Finding[]>({
    queryKey: [...pKeys.findings(pid), includeArchived],
    queryFn: () =>
      call(
        api.GET("/api/projects/{project_id}/research/findings", {
          params: { path: { project_id: pid }, query: { include_archived: includeArchived } },
        }),
      ),
  });
}

export function useResearchProviders() {
  return useQuery<ResearchProvider[]>({
    queryKey: pKeys.providers,
    queryFn: () => call(api.GET("/api/research/providers")),
  });
}

export function useSetResearchProviders() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: Schemas["ResearchProvidersIn"]) => call(api.PUT("/api/research/providers", { body })),
    onSuccess: invalidate,
  });
}

export function useResearchActions(pid: string) {
  const invalidate = useInvalidate();
  const qc = useQueryClient();
  return {
    add: useMutation({
      mutationFn: (body: FindingIn) =>
        call(api.POST("/api/projects/{project_id}/research/findings", { ...path(pid), body })),
      onSuccess: invalidate,
    }),
    patch: useMutation({
      mutationFn: ({ id, ...body }: Schemas["FindingPatch"] & { id: string }) =>
        call(
          api.PATCH("/api/projects/{project_id}/research/findings/{finding_id}", {
            params: { path: { project_id: pid, finding_id: id } },
            body,
          }),
        ),
      onSuccess: invalidate,
    }),
    search: useMutation({
      mutationFn: (body: Schemas["ResearchSearchIn"]) =>
        call(api.POST("/api/projects/{project_id}/research/search", { ...path(pid), body })),
      onSettled: () => void qc.invalidateQueries({ queryKey: ["activity"] }),
    }),
    save: useMutation({
      mutationFn: (body: Schemas["SaveHitIn"]) =>
        call(api.POST("/api/projects/{project_id}/research/save", { ...path(pid), body })),
      onSuccess: invalidate,
    }),
    ideas: useMutation({
      mutationFn: (body: Schemas["ResearchIdeasIn"]) =>
        call(api.POST("/api/projects/{project_id}/research/ideas", { ...path(pid), body })),
      onSuccess: () => void qc.invalidateQueries({ queryKey: ["ai"] }),
    }),
  };
}

export function useOutlines(pid: string) {
  return useQuery<Outline[]>({
    queryKey: pKeys.outlines(pid),
    queryFn: () => call(api.GET("/api/projects/{project_id}/outlines", path(pid))),
  });
}

export function useOutlineActions(pid: string) {
  const invalidate = useInvalidate();
  const qc = useQueryClient();
  const vpath = (oid: string) => ({ params: { path: { project_id: pid, outline_id: oid } } });
  return {
    saveDraft: useMutation({
      mutationFn: (body: Schemas["OutlineDraftIn"]) =>
        call(api.PUT("/api/projects/{project_id}/outlines/draft", { ...path(pid), body })),
      onSuccess: invalidate,
    }),
    generate: useMutation({
      mutationFn: (body: Schemas["OutlineGenerateIn"]) =>
        call(api.POST("/api/projects/{project_id}/outlines/generate", { ...path(pid), body })),
      onSuccess: () => void qc.invalidateQueries({ queryKey: ["ai"] }),
    }),
    edit: useMutation({
      mutationFn: (oid: string) =>
        call(api.POST("/api/projects/{project_id}/outlines/{outline_id}/edit", vpath(oid))),
      onSuccess: invalidate,
    }),
    approve: useMutation({
      mutationFn: (oid: string) =>
        call(api.POST("/api/projects/{project_id}/outlines/{outline_id}/approve", vpath(oid))),
      onSuccess: invalidate,
    }),
    reject: useMutation({
      mutationFn: (oid: string) =>
        call(api.POST("/api/projects/{project_id}/outlines/{outline_id}/reject", vpath(oid))),
      onSuccess: invalidate,
    }),
    apply: useMutation({
      mutationFn: (oid: string) =>
        call(api.POST("/api/projects/{project_id}/outlines/{outline_id}/apply", vpath(oid))),
      onSuccess: () => {
        invalidate();
        void qc.invalidateQueries({ queryKey: ["chapters"] });
        void qc.invalidateQueries({ queryKey: ["projects"] });
      },
    }),
  };
}

export function useRuns(pid: string) {
  return useQuery<Run[]>({
    queryKey: pKeys.runs(pid),
    queryFn: () => call(api.GET("/api/projects/{project_id}/runs", path(pid))),
    refetchInterval: (q) => ((q.state.data ?? []).some((r) => r.status === "running") ? 2000 : false),
  });
}

export function useRunActions(pid: string) {
  const invalidate = useInvalidate();
  const qc = useQueryClient();
  return {
    estimate: useMutation({
      mutationFn: (body: PlanRequest) =>
        call(api.POST("/api/projects/{project_id}/runs/estimate", { ...path(pid), body })),
    }),
    start: useMutation({
      mutationFn: (body: PlanRequest) =>
        call(api.POST("/api/projects/{project_id}/runs", { ...path(pid), body })),
      onSuccess: () => {
        invalidate();
        void qc.invalidateQueries({ queryKey: ["ai"] });
      },
    }),
    stop: useMutation({
      mutationFn: (rid: string) =>
        call(
          api.POST("/api/projects/{project_id}/runs/{run_id}/stop", {
            params: { path: { project_id: pid, run_id: rid } },
          }),
        ),
      onSuccess: () => {
        invalidate();
        void qc.invalidateQueries({ queryKey: ["ai"] });
      },
    }),
  };
}

export const BOOK_KIND_OF: Record<string, Brief["kind"]> = {
  fiction: "fiction",
  serial: "fiction",
  memoir: "memoir",
  workbook: "workbook",
  course: "manual",
  technical: "manual",
  nonfiction: "nonfiction",
};

export const FINDING_KINDS: { value: Finding["kind"]; label: string }[] = [
  { value: "note", label: "Note" },
  { value: "heuristic", label: "Observation (heuristic)" },
  { value: "measured", label: "Measured evidence (needs its source)" },
  { value: "competitor", label: "Comparable title" },
  { value: "keyword", label: "Keyword idea" },
  { value: "topic", label: "Topic idea" },
  { value: "query", label: "Search query" },
];

export const FLAG_TEXT: Record<string, string> = {
  ai_brainstorm_not_measured: "AI brainstorm: an idea, not evidence",
  removed_unsupported_metric: "A sales, ranking or demand claim was removed: no licensed source is connected",
  no_search_volume_data: "No search-volume data: none is available",
  unsourced_metric: "Looks like a market figure with no source: treat it as an opinion",
};
