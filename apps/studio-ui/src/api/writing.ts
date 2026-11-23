import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, call, type Schemas } from "./client";

export type DraftPlan = Schemas["PlanOut"];
export type DraftSection = Schemas["SectionOut"];
export type JobHistory = Schemas["JobHistoryOut"];
export type Fact = Schemas["FactOut"];
export type FactIn = Schemas["FactIn"];
export type Summary = Schemas["SummaryOut"];
export type QualityFinding = Schemas["QualityFindingOut"];
export type QualityRun = Schemas["QualityRunOut"];
export type WritingSettings = Schemas["WritingSettingsOut"];
export type Originality = Schemas["OriginalityOut"];

export const wKeys = {
  plans: (pid: string) => ["writing", "plans", pid] as const,
  history: (pid: string, planId: string) => ["writing", "history", pid, planId] as const,
  facts: (pid: string) => ["writing", "facts", pid] as const,
  summaries: (pid: string) => ["writing", "summaries", pid] as const,
  findings: (pid: string) => ["writing", "findings", pid] as const,
  settings: (pid: string) => ["writing", "settings", pid] as const,
  originality: (pid: string) => ["writing", "originality", pid] as const,
};

const path = (pid: string) => ({ params: { path: { project_id: pid } } });
const planPath = (pid: string, planId: string) => ({
  params: { path: { project_id: pid, plan_id: planId } },
});
const ACTIVE = ["waiting", "running"];

function useInvalidate() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["writing"] });
    void qc.invalidateQueries({ queryKey: ["planning"] });
    void qc.invalidateQueries({ queryKey: ["ai"] });
    void qc.invalidateQueries({ queryKey: ["activity"] });
  };
}

export function usePlans(pid: string) {
  return useQuery<DraftPlan[]>({
    queryKey: wKeys.plans(pid),
    queryFn: () => call(api.GET("/api/projects/{project_id}/writing/plans", path(pid))),
    refetchInterval: (q) => ((q.state.data ?? []).some((p) => ACTIVE.includes(p.status)) ? 1500 : false),
  });
}

export function usePlanHistory(pid: string, planId: string, enabled: boolean) {
  return useQuery<JobHistory[]>({
    queryKey: wKeys.history(pid, planId),
    queryFn: () =>
      call(api.GET("/api/projects/{project_id}/writing/plans/{plan_id}/history", planPath(pid, planId))),
    enabled,
  });
}

export function usePlanActions(pid: string) {
  const invalidate = useInvalidate();
  return {
    pause: useMutation({
      mutationFn: (planId: string) =>
        call(api.POST("/api/projects/{project_id}/writing/plans/{plan_id}/pause", planPath(pid, planId))),
      onSuccess: invalidate,
    }),
    resume: useMutation({
      mutationFn: (planId: string) =>
        call(api.POST("/api/projects/{project_id}/writing/plans/{plan_id}/resume", planPath(pid, planId))),
      onSuccess: invalidate,
    }),
    cancel: useMutation({
      mutationFn: (planId: string) =>
        call(api.POST("/api/projects/{project_id}/writing/plans/{plan_id}/cancel", planPath(pid, planId))),
      onSuccess: invalidate,
    }),
    retry: useMutation({
      mutationFn: ({ planId, sectionId }: { planId: string; sectionId: string }) =>
        call(
          api.POST("/api/projects/{project_id}/writing/plans/{plan_id}/sections/{section_id}/retry", {
            params: { path: { project_id: pid, plan_id: planId, section_id: sectionId } },
          }),
        ),
      onSuccess: invalidate,
    }),
    approve: useMutation({
      mutationFn: ({ planId, sectionId, edited }: { planId: string; sectionId: string; edited?: string }) =>
        call(
          api.POST("/api/projects/{project_id}/writing/plans/{plan_id}/sections/{section_id}/approve", {
            params: { path: { project_id: pid, plan_id: planId, section_id: sectionId } },
            body: edited !== undefined ? { edited_md: edited } : {},
          }),
        ),
      onSuccess: invalidate,
    }),
  };
}

export function useFacts(pid: string) {
  return useQuery<Fact[]>({
    queryKey: wKeys.facts(pid),
    queryFn: () => call(api.GET("/api/projects/{project_id}/writing/facts", path(pid))),
  });
}

export function useFactActions(pid: string) {
  const invalidate = useInvalidate();
  return {
    add: useMutation({
      mutationFn: (body: FactIn) =>
        call(api.POST("/api/projects/{project_id}/writing/facts", { ...path(pid), body })),
      onSuccess: invalidate,
    }),
    patch: useMutation({
      mutationFn: ({ id, body }: { id: string; body: Schemas["FactPatch"] }) =>
        call(
          api.PATCH("/api/projects/{project_id}/writing/facts/{fact_id}", {
            params: { path: { project_id: pid, fact_id: id } },
            body,
          }),
        ),
      onSuccess: invalidate,
    }),
  };
}

export function useSummaries(pid: string) {
  return useQuery<Summary[]>({
    queryKey: wKeys.summaries(pid),
    queryFn: () => call(api.GET("/api/projects/{project_id}/writing/summaries", path(pid))),
  });
}

export function usePutSummary(pid: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ chapterId, text }: { chapterId: string; text: string }) =>
      call(
        api.PUT("/api/projects/{project_id}/writing/summaries/{chapter_id}", {
          params: { path: { project_id: pid, chapter_id: chapterId } },
          body: { text },
        }),
      ),
    onSuccess: invalidate,
  });
}

export function useFindings(pid: string) {
  return useQuery<QualityFinding[]>({
    queryKey: wKeys.findings(pid),
    queryFn: () => call(api.GET("/api/projects/{project_id}/writing/quality", path(pid))),
  });
}

export function useQualityActions(pid: string) {
  const invalidate = useInvalidate();
  return {
    run: useMutation({
      mutationFn: (body: Schemas["QualityRunIn"]) =>
        call(api.POST("/api/projects/{project_id}/writing/quality/run", { ...path(pid), body })),
      onSuccess: invalidate,
    }),
    patch: useMutation({
      mutationFn: ({ id, body }: { id: string; body: Schemas["FindingPatchIn"] }) =>
        call(
          api.PATCH("/api/projects/{project_id}/writing/quality/{finding_id}", {
            params: { path: { project_id: pid, finding_id: id } },
            body,
          }),
        ),
      onSuccess: invalidate,
    }),
    aiReview: useMutation({
      mutationFn: (body: Schemas["AiReviewIn"]) =>
        call(api.POST("/api/projects/{project_id}/writing/quality/ai-review", { ...path(pid), body })),
      onSuccess: invalidate,
    }),
  };
}

export function useWritingSettings(pid: string) {
  return useQuery<WritingSettings>({
    queryKey: wKeys.settings(pid),
    queryFn: () => call(api.GET("/api/projects/{project_id}/writing/settings", path(pid))),
  });
}

export function useSetWritingSettings(pid: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: Schemas["WritingSettingsIn"]) =>
      call(api.PUT("/api/projects/{project_id}/writing/settings", { ...path(pid), body })),
    onSuccess: invalidate,
  });
}

export function useOriginality(pid: string, enabled: boolean) {
  return useQuery<Originality>({
    queryKey: wKeys.originality(pid),
    queryFn: () => call(api.GET("/api/projects/{project_id}/writing/originality", path(pid))),
    enabled,
  });
}

export const PLAN_STATUS: Record<DraftPlan["status"], string> = {
  waiting: "Waiting for the previous chapter",
  running: "Drafting",
  paused: "Paused",
  awaiting_review: "Waiting for your review",
  ready: "Ready for review in the chapter",
  cancelled: "Cancelled",
};

export const SECTION_STATE: Record<DraftSection["state"], string> = {
  pending: "Not started",
  queued: "Queued",
  running: "Drafting now",
  done: "Done",
  failed: "Failed",
  cancelled: "Stopped",
};

export const FINDING_STATES: { value: QualityFinding["state"]; label: string }[] = [
  { value: "open", label: "Open" },
  { value: "needs_source", label: "Needs a source" },
  { value: "will_fix", label: "I will fix it" },
  { value: "dismissed", label: "Dismissed (fine as it is)" },
  { value: "fixed", label: "Fixed" },
];

export const FACT_KINDS: { value: Fact["kind"]; label: string }[] = [
  { value: "character", label: "Character" },
  { value: "location", label: "Place" },
  { value: "relationship", label: "Relationship" },
  { value: "event", label: "Event (timeline)" },
  { value: "thread", label: "Open story thread" },
  { value: "term", label: "Term" },
  { value: "other", label: "Other" },
];
