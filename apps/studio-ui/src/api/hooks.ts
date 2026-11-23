import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  call,
  type Activity,
  type Capability,
  type Chapter,
  type ChapterContent,
  type ChapterStatus,
  type ExportRun,
  type Project,
  type ProjectCreate,
  type ProjectPatch,
  type PublicationFormat,
  type ProjectType,
  type Schemas,
  type SystemInfo,
} from "./client";

export interface LibraryQuery {
  q?: string;
  project_type?: ProjectType;
  publication_format?: PublicationFormat;
  status?: "active" | "archived" | "all";
  sort?:
    "title" | "project_type" | "language" | "audience" | "target_word_count" | "updated_at" | "created_at";
  order?: "asc" | "desc";
}

export const keys = {
  projects: ["projects"] as const,
  projectList: (q: LibraryQuery) => ["projects", "list", q] as const,
  project: (id: string) => ["projects", "one", id] as const,
  chapters: (pid: string) => ["chapters", pid] as const,
  content: (pid: string, cid: string) => ["content", pid, cid] as const,
  exports: (pid: string) => ["exports", pid] as const,
  activity: (pid?: string) => ["activity", pid ?? "all"] as const,
  system: ["system"] as const,
  capabilities: ["capabilities"] as const,
};

export function useProjects(q: LibraryQuery) {
  return useQuery({
    queryKey: keys.projectList(q),
    queryFn: () => call(api.GET("/api/projects", { params: { query: { ...q, limit: 200 } } })),
  });
}

export function useProject(id: string) {
  return useQuery<Project>({
    queryKey: keys.project(id),
    queryFn: () => call(api.GET("/api/projects/{project_id}", { params: { path: { project_id: id } } })),
  });
}

function useInvalidateProjects() {
  const qc = useQueryClient();
  return (projectId?: string) => {
    void qc.invalidateQueries({ queryKey: keys.projects });
    void qc.invalidateQueries({ queryKey: ["activity"] });
    if (projectId) {
      void qc.invalidateQueries({ queryKey: keys.chapters(projectId) });
      void qc.invalidateQueries({ queryKey: keys.exports(projectId) });
    }
  };
}

export function useCreateProject() {
  const invalidate = useInvalidateProjects();
  return useMutation({
    mutationFn: (body: ProjectCreate) => call(api.POST("/api/projects", { body })),
    onSuccess: () => invalidate(),
  });
}

export function useUpdateProject(id: string) {
  const invalidate = useInvalidateProjects();
  return useMutation({
    mutationFn: (body: ProjectPatch) =>
      call(api.PATCH("/api/projects/{project_id}", { params: { path: { project_id: id } }, body })),
    onSuccess: () => invalidate(id),
  });
}

export function useSetArchived(id: string) {
  const invalidate = useInvalidateProjects();
  return useMutation({
    mutationFn: (archived: boolean) =>
      archived
        ? call(api.POST("/api/projects/{project_id}/archive", { params: { path: { project_id: id } } }))
        : call(api.POST("/api/projects/{project_id}/unarchive", { params: { path: { project_id: id } } })),
    onSuccess: () => invalidate(id),
  });
}

export function useDuplicateProject(id: string) {
  const invalidate = useInvalidateProjects();
  return useMutation({
    mutationFn: () =>
      call(api.POST("/api/projects/{project_id}/duplicate", { params: { path: { project_id: id } } })),
    onSuccess: () => invalidate(),
  });
}

export function useChapters(pid: string) {
  return useQuery<Chapter[]>({
    queryKey: keys.chapters(pid),
    queryFn: () =>
      call(api.GET("/api/projects/{project_id}/chapters", { params: { path: { project_id: pid } } })),
  });
}

export function useCreateChapter(pid: string) {
  const invalidate = useInvalidateProjects();
  return useMutation({
    mutationFn: (title: string) =>
      call(
        api.POST("/api/projects/{project_id}/chapters", {
          params: { path: { project_id: pid } },
          body: { title, kind: "chapter" },
        }),
      ),
    onSuccess: () => invalidate(pid),
  });
}

export function useUpdateChapter(pid: string) {
  const invalidate = useInvalidateProjects();
  return useMutation({
    mutationFn: ({
      cid,
      ...body
    }: {
      cid: string;
      title?: string;
      status?: ChapterStatus;
      locked?: boolean;
    }) =>
      call(
        api.PATCH("/api/projects/{project_id}/chapters/{chapter_id}", {
          params: { path: { project_id: pid, chapter_id: cid } },
          body,
        }),
      ),
    onSuccess: () => invalidate(pid),
  });
}

export function useArchiveChapter(pid: string) {
  const invalidate = useInvalidateProjects();
  return useMutation({
    mutationFn: (cid: string) =>
      call(
        api.POST("/api/projects/{project_id}/chapters/{chapter_id}/archive", {
          params: { path: { project_id: pid, chapter_id: cid } },
        }),
      ),
    onSuccess: () => invalidate(pid),
  });
}

export function useChapter(pid: string, cid: string) {
  return useQuery<Chapter>({
    queryKey: [...keys.chapters(pid), cid],
    queryFn: () =>
      call(
        api.GET("/api/projects/{project_id}/chapters/{chapter_id}", {
          params: { path: { project_id: pid, chapter_id: cid } },
        }),
      ),
  });
}

export function useChapterContent(pid: string, cid: string) {
  return useQuery<ChapterContent>({
    queryKey: keys.content(pid, cid),
    queryFn: () =>
      call(
        api.GET("/api/projects/{project_id}/chapters/{chapter_id}/content", {
          params: { path: { project_id: pid, chapter_id: cid } },
        }),
      ),
    refetchOnWindowFocus: false,
    staleTime: Infinity,
  });
}

export function useSaveContent(pid: string, cid: string) {
  const qc = useQueryClient();
  const invalidate = useInvalidateProjects();
  return useMutation({
    mutationFn: (body: Schemas["ChapterSaveIn"]) =>
      call(
        api.PUT("/api/projects/{project_id}/chapters/{chapter_id}/content", {
          params: { path: { project_id: pid, chapter_id: cid } },
          body,
        }),
      ),
    onSuccess: (result) => {
      qc.setQueryData(keys.content(pid, cid), result.content);
      invalidate(pid);
    },
  });
}

export function useExports(pid: string) {
  return useQuery<ExportRun[]>({
    queryKey: keys.exports(pid),
    queryFn: () =>
      call(api.GET("/api/projects/{project_id}/exports", { params: { path: { project_id: pid } } })),
  });
}

export function useCreateExport(pid: string) {
  const invalidate = useInvalidateProjects();
  return useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/projects/{project_id}/exports", {
          params: { path: { project_id: pid } },
          body: { format: "markdown" },
        }),
      ),
    onSuccess: () => invalidate(pid),
  });
}

export function useActivity(projectId?: string, limit = 50) {
  return useQuery<Activity[]>({
    queryKey: [...keys.activity(projectId), limit],
    queryFn: () =>
      call(api.GET("/api/activity", { params: { query: { project_id: projectId ?? null, limit } } })),
  });
}

export function useSystemInfo() {
  return useQuery<SystemInfo>({
    queryKey: keys.system,
    queryFn: () => call(api.GET("/api/system/info")),
    staleTime: 60_000,
  });
}

export function useCapabilities() {
  return useQuery<Capability[]>({
    queryKey: keys.capabilities,
    queryFn: () => call(api.GET("/api/system/capabilities")),
  });
}
