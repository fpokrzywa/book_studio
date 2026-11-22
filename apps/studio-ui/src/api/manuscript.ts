import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, call, upload, type Schemas } from "./client";
import { keys } from "./hooks";

export type Chapter = Schemas["ChapterOut"];
export type ChapterContent = Schemas["ChapterContentOut"];
export type RevisionMeta = Schemas["RevisionMetaOut"];
export type Revision = Schemas["RevisionOut"];
export type Compare = Schemas["CompareOut"];
export type Preview = Schemas["PreviewOut"];
export type Asset = Schemas["AssetOut"];
export type ImportPreview = Schemas["ImportPreviewOut"];
export type ImportCommit = Schemas["ImportCommitIn"];
export type Backup = Schemas["BackupOut"];
export type Restored = Schemas["RestoreOut"];

const chapterPath = (pid: string, cid: string) => ({
  params: { path: { project_id: pid, chapter_id: cid } },
});

function useInvalidate(pid: string) {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: keys.chapters(pid) });
    void qc.invalidateQueries({ queryKey: ["projects"] });
    void qc.invalidateQueries({ queryKey: ["activity"] });
    void qc.invalidateQueries({ queryKey: ["revisions", pid] });
  };
}

export function useMoveChapter(pid: string) {
  const invalidate = useInvalidate(pid);
  return useMutation({
    mutationFn: ({ cid, parentId, index }: { cid: string; parentId: string | null; index: number }) =>
      call(
        api.POST("/api/projects/{project_id}/chapters/{chapter_id}/move", {
          ...chapterPath(pid, cid),
          body: { parent_id: parentId, index },
        }),
      ),
    onSuccess: invalidate,
  });
}

export function useCreateSection(pid: string) {
  const invalidate = useInvalidate(pid);
  return useMutation({
    mutationFn: (body: { title: string; parent_id: string | null; kind: Chapter["kind"] }) =>
      call(api.POST("/api/projects/{project_id}/chapters", { params: { path: { project_id: pid } }, body })),
    onSuccess: invalidate,
  });
}

export function usePatchChapter(pid: string) {
  const invalidate = useInvalidate(pid);
  return useMutation({
    mutationFn: ({ cid, ...body }: { cid: string } & Schemas["ChapterPatch"]) =>
      call(api.PATCH("/api/projects/{project_id}/chapters/{chapter_id}", { ...chapterPath(pid, cid), body })),
    onSuccess: invalidate,
  });
}

export function useSaveDraft(pid: string, cid: string) {
  return useMutation({
    mutationFn: (body: Schemas["DraftIn"]) =>
      call(
        api.PUT("/api/projects/{project_id}/chapters/{chapter_id}/draft", { ...chapterPath(pid, cid), body }),
      ),
  });
}

export function useDiscardDraft(pid: string, cid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      call(api.DELETE("/api/projects/{project_id}/chapters/{chapter_id}/draft", chapterPath(pid, cid))),
    onSuccess: (content) => qc.setQueryData(keys.content(pid, cid), content),
  });
}

export function useRevisions(pid: string, cid: string, enabled = true) {
  return useQuery<RevisionMeta[]>({
    queryKey: ["revisions", pid, cid],
    enabled,
    queryFn: () =>
      call(api.GET("/api/projects/{project_id}/chapters/{chapter_id}/revisions", chapterPath(pid, cid))),
  });
}

export function useCompare(pid: string, cid: string, from: number | null, to: number | null) {
  return useQuery<Compare>({
    queryKey: ["compare", pid, cid, from, to],
    enabled: from !== null && to !== null && from !== to,
    queryFn: () =>
      call(
        api.GET("/api/projects/{project_id}/chapters/{chapter_id}/compare", {
          params: { path: { project_id: pid, chapter_id: cid }, query: { from: from ?? 1, to: to ?? 1 } },
        }),
      ),
  });
}

export function useRestoreRevision(pid: string, cid: string) {
  const invalidate = useInvalidate(pid);
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      revisionNo,
      expectedHeadNo,
      note,
    }: {
      revisionNo: number;
      expectedHeadNo: number;
      note?: string;
    }) =>
      call(
        api.POST("/api/projects/{project_id}/chapters/{chapter_id}/revisions/{revision_no}/restore", {
          params: { path: { project_id: pid, chapter_id: cid, revision_no: revisionNo } },
          body: { expected_head_no: expectedHeadNo, note: note ?? null },
        }),
      ),
    onSuccess: (result) => {
      qc.setQueryData(keys.content(pid, cid), result.content);
      invalidate();
    },
  });
}

export function useTagRevision(pid: string, cid: string) {
  const invalidate = useInvalidate(pid);
  return useMutation({
    mutationFn: ({
      revisionNo,
      label,
      note,
    }: {
      revisionNo: number;
      label: string | null;
      note: string | null;
    }) =>
      call(
        api.PUT("/api/projects/{project_id}/chapters/{chapter_id}/revisions/{revision_no}/tag", {
          params: { path: { project_id: pid, chapter_id: cid, revision_no: revisionNo } },
          body: { label, note },
        }),
      ),
    onSuccess: invalidate,
  });
}

export function usePreview(pid: string) {
  return useMutation({
    mutationFn: (source_md: string) =>
      call(
        api.POST("/api/projects/{project_id}/preview", {
          params: { path: { project_id: pid } },
          body: { source_md },
        }),
      ),
  });
}

export function useUploadAsset(pid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => upload<Asset>(`/api/projects/${pid}/assets`, file, file.name),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["assets", pid] }),
  });
}

export function useStartImport() {
  return useMutation({
    mutationFn: ({ file, targetProjectId }: { file: File; targetProjectId?: string }) =>
      upload<ImportPreview>(
        "/api/imports",
        file,
        file.name,
        targetProjectId ? { target_project_id: targetProjectId } : {},
      ),
  });
}

export function useCommitImport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ImportCommit }) =>
      call(api.POST("/api/imports/{import_id}/commit", { params: { path: { import_id: id } }, body })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["projects"] });
      void qc.invalidateQueries({ queryKey: ["chapters"] });
      void qc.invalidateQueries({ queryKey: ["activity"] });
    },
  });
}

export function useCancelImport() {
  return useMutation({
    mutationFn: (id: string) =>
      call(api.POST("/api/imports/{import_id}/cancel", { params: { path: { import_id: id } } })),
  });
}

export function useBackups(pid: string) {
  return useQuery<Backup[]>({
    queryKey: ["backups", pid],
    queryFn: () =>
      call(api.GET("/api/projects/{project_id}/backups", { params: { path: { project_id: pid } } })),
  });
}

export function useCreateBackup(pid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      call(api.POST("/api/projects/{project_id}/backups", { params: { path: { project_id: pid } } })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["backups", pid] });
      void qc.invalidateQueries({ queryKey: ["activity"] });
    },
  });
}

export function useRestoreBackup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => upload<Restored>("/api/backups/restore", file, file.name),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["projects"] });
      void qc.invalidateQueries({ queryKey: ["activity"] });
    },
  });
}

export function useExportAs(pid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (format: "markdown" | "html") =>
      call(
        api.POST("/api/projects/{project_id}/exports", {
          params: { path: { project_id: pid } },
          body: { format },
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.exports(pid) });
      void qc.invalidateQueries({ queryKey: ["activity"] });
    },
  });
}
