import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, call, upload, type Schemas } from "./client";

export type Library = Schemas["LibraryOut"];
export type Source = Schemas["SourceOut"];
export type SourcePatch = Schemas["SourcePatch"];
export type SourceImport = Schemas["SourceImportOut"];
export type SearchResult = Schemas["SearchOut"];
export type SearchHit = Schemas["SearchHitOut"];
export type SourceText = Schemas["SourceTextOut"];
export type BookKnowledge = Schemas["BookKnowledgeOut"];
export type Citation = Schemas["CitationOut"];
export type Claim = Schemas["ClaimOut"];
export type ClaimSupport = Schemas["SupportOut"];
export type Profile = Schemas["AuthorProfileOut"];
export type Interview = Schemas["InterviewOut"];

export const kKeys = {
  book: (pid: string) => ["knowledge", "book", pid] as const,
  bookSources: (pid: string) => ["knowledge", "sources", "book", pid] as const,
  libSources: (lid: string) => ["knowledge", "sources", "lib", lid] as const,
  shared: ["knowledge", "shared"] as const,
  source: (sid: string) => ["knowledge", "source", sid] as const,
  sourceText: (sid: string) => ["knowledge", "text", sid] as const,
  search: (scope: string, q: string) => ["knowledge", "search", scope, q] as const,
  citations: (pid: string) => ["knowledge", "citations", pid] as const,
  claims: (pid: string, proposed: boolean) => ["evidence", pid, proposed] as const,
  profiles: ["voice"] as const,
  interview: (pid: string) => ["interview", pid] as const,
};

function useInvalidate() {
  const qc = useQueryClient();
  return (...prefixes: string[]) => {
    for (const p of prefixes) void qc.invalidateQueries({ queryKey: [p] });
    void qc.invalidateQueries({ queryKey: ["activity"] });
  };
}

// ---------- book knowledge ----------

export function useBookKnowledge(pid: string, enabled = true) {
  return useQuery<BookKnowledge>({
    queryKey: kKeys.book(pid),
    queryFn: () =>
      call(api.GET("/api/projects/{project_id}/knowledge", { params: { path: { project_id: pid } } })),
    enabled,
  });
}

export function useBookSources(pid: string, includeRemoved = false) {
  return useQuery<Source[]>({
    queryKey: [...kKeys.bookSources(pid), includeRemoved],
    queryFn: () =>
      call(
        api.GET("/api/projects/{project_id}/knowledge/sources", {
          params: { path: { project_id: pid }, query: { include_removed: includeRemoved } },
        }),
      ),
  });
}

export function useImportToBook(pid: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ file, allowDuplicate }: { file: File; allowDuplicate?: boolean }) =>
      upload<SourceImport>(`/api/projects/${pid}/knowledge/sources`, file, file.name, {
        allow_duplicate: allowDuplicate ? "true" : "false",
      }),
    onSuccess: () => invalidate("knowledge"),
  });
}

export function useLinkLibrary(pid: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ libraryId, on }: { libraryId: string; on: boolean }) => {
      const params = { params: { path: { project_id: pid, library_id: libraryId } } };
      return call(
        on
          ? api.PUT("/api/projects/{project_id}/knowledge/links/{library_id}", params)
          : api.DELETE("/api/projects/{project_id}/knowledge/links/{library_id}", params),
      );
    },
    onSuccess: () => invalidate("knowledge"),
  });
}

export function useSearch(scope: { projectId?: string; libraryId?: string }, q: string) {
  const key = scope.projectId ? `p:${scope.projectId}` : `l:${scope.libraryId}`;
  return useQuery<SearchResult>({
    queryKey: kKeys.search(key, q),
    queryFn: () =>
      scope.projectId
        ? call(
            api.GET("/api/projects/{project_id}/knowledge/search", {
              params: { path: { project_id: scope.projectId }, query: { q } },
            }),
          )
        : call(
            api.GET("/api/knowledge/libraries/{library_id}/search", {
              params: { path: { library_id: scope.libraryId ?? "" }, query: { q } },
            }),
          ),
    enabled: q.trim().length > 0,
  });
}

// ---------- shared libraries ----------

export function useSharedLibraries() {
  return useQuery<Library[]>({
    queryKey: kKeys.shared,
    queryFn: () => call(api.GET("/api/knowledge/libraries")),
  });
}

export function useCreateLibrary() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: Schemas["LibraryCreate"]) => call(api.POST("/api/knowledge/libraries", { body })),
    onSuccess: () => invalidate("knowledge"),
  });
}

export function useLibrarySources(lid: string) {
  return useQuery<Source[]>({
    queryKey: kKeys.libSources(lid),
    queryFn: () =>
      call(
        api.GET("/api/knowledge/libraries/{library_id}/sources", { params: { path: { library_id: lid } } }),
      ),
  });
}

export function useImportToLibrary(lid: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ file, allowDuplicate }: { file: File; allowDuplicate?: boolean }) =>
      upload<SourceImport>(`/api/knowledge/libraries/${lid}/sources`, file, file.name, {
        allow_duplicate: allowDuplicate ? "true" : "false",
      }),
    onSuccess: () => invalidate("knowledge"),
  });
}

// ---------- one source ----------

export function useSourceText(sid: string) {
  return useQuery<SourceText>({
    queryKey: kKeys.sourceText(sid),
    queryFn: () =>
      call(api.GET("/api/knowledge/sources/{source_id}/text", { params: { path: { source_id: sid } } })),
  });
}

export function useSourceActions() {
  const invalidate = useInvalidate();
  const path = (sid: string) => ({ params: { path: { source_id: sid } } });
  const opts = { onSuccess: () => invalidate("knowledge", "evidence") };
  return {
    patch: useMutation({
      mutationFn: ({ id, ...body }: SourcePatch & { id: string }) =>
        call(api.PATCH("/api/knowledge/sources/{source_id}", { ...path(id), body })),
      ...opts,
    }),
    remove: useMutation({
      mutationFn: (id: string) => call(api.DELETE("/api/knowledge/sources/{source_id}", path(id))),
      ...opts,
    }),
    reindex: useMutation({
      mutationFn: (id: string) => call(api.POST("/api/knowledge/sources/{source_id}/reindex", path(id))),
      ...opts,
    }),
  };
}

export function useCitations(pid: string) {
  return useQuery<Citation[]>({
    queryKey: kKeys.citations(pid),
    queryFn: () =>
      call(api.GET("/api/projects/{project_id}/citations", { params: { path: { project_id: pid } } })),
  });
}

// ---------- evidence ledger ----------

export function useClaims(pid: string, includeProposed = false) {
  return useQuery<Claim[]>({
    queryKey: kKeys.claims(pid, includeProposed),
    queryFn: () =>
      call(
        api.GET("/api/projects/{project_id}/claims", {
          params: { path: { project_id: pid }, query: { include_proposed: includeProposed } },
        }),
      ),
  });
}

export function useClaimActions(pid: string) {
  const invalidate = useInvalidate();
  return {
    create: useMutation({
      mutationFn: (body: Schemas["ClaimCreate"]) =>
        call(api.POST("/api/projects/{project_id}/claims", { params: { path: { project_id: pid } }, body })),
      onSuccess: () => invalidate("evidence"),
    }),
    patch: useMutation({
      mutationFn: ({ id, ...body }: Schemas["ClaimPatch"] & { id: string }) =>
        call(
          api.PATCH("/api/projects/{project_id}/claims/{claim_id}", {
            params: { path: { project_id: pid, claim_id: id } },
            body,
          }),
        ),
      onSuccess: () => invalidate("evidence"),
    }),
  };
}

// ---------- author voice ----------

export function useProfiles() {
  return useQuery<Profile[]>({
    queryKey: kKeys.profiles,
    queryFn: () => call(api.GET("/api/voice/profiles")),
  });
}

export function useProfileActions() {
  const invalidate = useInvalidate();
  const opts = { onSuccess: () => invalidate("voice") };
  const path = (id: string) => ({ params: { path: { profile_id: id } } });
  return {
    create: useMutation({
      mutationFn: (body: Schemas["AuthorProfileCreate"]) => call(api.POST("/api/voice/profiles", { body })),
      ...opts,
    }),
    patch: useMutation({
      mutationFn: ({ id, ...body }: Schemas["AuthorProfilePatch"] & { id: string }) =>
        call(api.PATCH("/api/voice/profiles/{profile_id}", { ...path(id), body })),
      ...opts,
    }),
    addSample: useMutation({
      mutationFn: ({ id, ...body }: Schemas["VoiceSampleIn"] & { id: string }) =>
        call(api.POST("/api/voice/profiles/{profile_id}/samples", { ...path(id), body })),
      ...opts,
    }),
    addFile: useMutation({
      mutationFn: ({ id, file, basis }: { id: string; file: File; basis: string }) =>
        upload<Profile>(`/api/voice/profiles/${id}/samples/file`, file, file.name, {
          rights_confirmed: "true",
          rights_basis: basis,
        }),
      ...opts,
    }),
    removeSample: useMutation({
      mutationFn: ({ id, sampleId }: { id: string; sampleId: string }) =>
        call(
          api.DELETE("/api/voice/profiles/{profile_id}/samples/{sample_id}", {
            params: { path: { profile_id: id, sample_id: sampleId } },
          }),
        ),
      ...opts,
    }),
  };
}

// ---------- interview ----------

export function useInterview(pid: string) {
  return useQuery<Interview>({
    queryKey: kKeys.interview(pid),
    queryFn: () =>
      call(api.GET("/api/projects/{project_id}/interview", { params: { path: { project_id: pid } } })),
  });
}

export function useInterviewActions(pid: string) {
  const qc = useQueryClient();
  const set = (data: Interview) => qc.setQueryData(kKeys.interview(pid), data);
  return {
    answer: useMutation({
      mutationFn: ({ questionId, answer_text }: { questionId: string; answer_text: string }) =>
        call(
          api.PUT("/api/projects/{project_id}/interview/questions/{question_id}/answer", {
            params: { path: { project_id: pid, question_id: questionId } },
            body: { answer_text },
          }),
        ),
      onSuccess: set,
    }),
    addQuestion: useMutation({
      mutationFn: (prompt: string) =>
        call(
          api.POST("/api/projects/{project_id}/interview/questions", {
            params: { path: { project_id: pid } },
            body: { prompt },
          }),
        ),
      onSuccess: set,
    }),
  };
}

export const STATUS_TEXT: Record<Source["status"], string> = {
  pending: "Waiting to index",
  indexed: "Searchable",
  failed: "Could not be read",
};

export const TITLE_ORIGIN: Record<string, string> = {
  file_metadata: "from the file's own metadata",
  file_name: "from the file name",
  first_heading: "from the first heading",
  author: "set by you",
};
