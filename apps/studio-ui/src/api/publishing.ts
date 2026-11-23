import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, call, runTask, type Schemas } from "./client";

export type Profile = Schemas["ProfileOut"];
export type ProfileIn = Schemas["ProfileIn"];
export type Publication = Schemas["PublicationOut"];
export type CoverSpec = Schemas["CoverSpecOut"];
export type PackageResult = Schemas["PackageOut"];
export type BuildFormat = Schemas["BuildIn"]["formats"][number];

const path = (pid: string) => ({ params: { path: { project_id: pid } } });
export const pubKeys = {
  profile: (pid: string) => ["publishing", "profile", pid] as const,
  pubs: (pid: string) => ["publishing", "pubs", pid] as const,
  cover: (pid: string) => ["publishing", "cover", pid] as const,
  preview: (pid: string) => ["publishing", "preview", pid] as const,
};

function useInvalidate() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["publishing"] });
    void qc.invalidateQueries({ queryKey: ["activity"] });
  };
}

export function usePublishingProfile(pid: string) {
  return useQuery<Profile>({
    queryKey: pubKeys.profile(pid),
    queryFn: () => call(api.GET("/api/projects/{project_id}/publishing/profile", path(pid))),
  });
}

export function useSaveProfile(pid: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: ProfileIn) =>
      call(api.PUT("/api/projects/{project_id}/publishing/profile", { ...path(pid), body })),
    onSuccess: invalidate,
  });
}

export function usePublications(pid: string) {
  return useQuery<Publication[]>({
    queryKey: pubKeys.pubs(pid),
    queryFn: () => call(api.GET("/api/projects/{project_id}/publishing/publications", path(pid))),
  });
}

export function useAssets(pid: string) {
  return useQuery({
    queryKey: ["publishing", "assets", pid],
    queryFn: () => call(api.GET("/api/projects/{project_id}/assets", path(pid))),
  });
}

export function useCoverSpec(pid: string) {
  return useQuery<CoverSpec>({
    queryKey: pubKeys.cover(pid),
    queryFn: () => call(api.GET("/api/projects/{project_id}/publishing/cover-spec", path(pid))),
  });
}

export function useHtmlPreview(pid: string, enabled: boolean) {
  return useQuery({
    queryKey: pubKeys.preview(pid),
    queryFn: () => call(api.GET("/api/projects/{project_id}/publishing/preview/html", path(pid))),
    enabled,
  });
}

export function usePublishActions(pid: string) {
  const invalidate = useInvalidate();
  return {
    build: useMutation({
      mutationFn: (formats: BuildFormat[]) =>
        runTask<Schemas["BuildOut"]>(
          call(
            api.POST("/api/projects/{project_id}/publishing/build-task", { ...path(pid), body: { formats } }),
          ),
        ),
      onSuccess: invalidate,
    }),
    covers: useMutation({
      mutationFn: () =>
        runTask<Schemas["BuildOut"]>(
          call(api.POST("/api/projects/{project_id}/publishing/covers-task", path(pid))),
        ),
      onSuccess: invalidate,
    }),
    pkg: useMutation({
      mutationFn: () =>
        runTask<Schemas["PackageOut"]>(
          call(api.POST("/api/projects/{project_id}/publishing/package-task", path(pid))),
        ),
      onSuccess: invalidate,
    }),
  };
}

export const fileUrl = (pid: string, pubId: string, inline = false) =>
  `/api/projects/${pid}/publishing/publications/${pubId}/file${inline ? "?inline=true" : ""}`;
export const reportUrl = (pid: string, pubId: string) =>
  `/api/projects/${pid}/publishing/publications/${pubId}/report.html`;
export const packageFileUrl = (pid: string, pubId: string, name: string, inline = false) =>
  `/api/projects/${pid}/publishing/publications/${pubId}/package-file?name=${encodeURIComponent(name)}${inline ? "&inline=true" : ""}`;
export const pdfPageUrl = (pid: string, page: number, nonce: number) =>
  `/api/projects/${pid}/publishing/preview/pdf-page/${page}?v=${nonce}`;

export const KIND_LABEL: Record<string, string> = {
  markdown: "Markdown (with images)",
  html: "HTML",
  epub: "EPUB",
  docx: "Word (DOCX)",
  pdf: "Print interior PDF",
  cover_print: "Print cover PDF",
  cover_proof: "Cover proof with guides (not for upload)",
  cover_ebook: "eBook cover (JPEG)",
  package: "Publish package (ZIP)",
};

export const STATUS_LABEL: Record<string, string> = {
  pass: "passed",
  warn: "warnings",
  fail: "failed",
  manual: "check by hand",
  unavailable: "could not check",
};
