/** Phase 08 API: series canon and continuity, pen names, translated editions, narration, recordings. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, call, runTask, upload, type Schemas } from "./client";

export type Series = Schemas["SeriesOut"];
export type Canon = Schemas["CanonOut"];
export type Entity = Schemas["EntityOut"];
export type Fact = Schemas["CanonFactOut"];
export type Relationship = Schemas["RelationshipOut"];
export type Issue = Schemas["IssueOut"];
export type ResolveAction = Schemas["ResolveIn"]["action"];
export type CanonKind = Schemas["EntityIn"]["kind"];
export type VoiceRule = Schemas["VoiceRule"];
export type ProjectVoice = Schemas["ProjectVoiceOut"];
export interface EditionIssue {
  kind: string;
  message: string;
  source: string;
  target: string;
  state: "open" | "reviewed" | "will_fix";
}
export interface EditionChapter {
  source_chapter_id: string;
  source_title: string;
  source_head_no: number;
  source_status: string;
  target_chapter_id: string;
  target_title: string;
  status: string;
  source_revision_no: number | null;
  stale: boolean;
  suggested_title: string | null;
  issues: EditionIssue[];
  proposal_id: string | null;
}
export type Edition = Omit<Schemas["EditionOut"], "chapters"> & { chapters: EditionChapter[] };
export interface LinkedChapter {
  project_id: string;
  project_title?: string;
  chapter_id: string;
  chapter_title: string;
  language: string;
  status: string;
  source_revision_no: number | null;
  stale?: boolean;
  link: string;
}
export type ChapterLinks = Omit<Schemas["ChapterLinksOut"], "translation_of" | "translations"> & {
  translation_of: LinkedChapter | null;
  translations: LinkedChapter[];
};
export type Narration = Schemas["NarrationOut"];
export type NarrationSettings = Schemas["NarrationSettingsIn"];
export type Recording = Schemas["RecordingOut"];
export type MediaStatus = Schemas["MediaStatusOut"];

const sp = (sid: string) => ({ params: { path: { series_id: sid } } });
const pp = (pid: string) => ({ params: { path: { project_id: pid } } });

function useInvalidate(...keys: string[]) {
  const qc = useQueryClient();
  return () => {
    for (const k of [...keys, "activity"]) void qc.invalidateQueries({ queryKey: [k] });
  };
}

// ---------- series ----------

export function useSeriesList() {
  return useQuery<Series[]>({ queryKey: ["series", "list"], queryFn: () => call(api.GET("/api/series")) });
}

export function useSeries(sid: string) {
  return useQuery<Series>({
    queryKey: ["series", sid],
    queryFn: () => call(api.GET("/api/series/{series_id}", sp(sid))),
  });
}

export function useCanon(sid: string) {
  return useQuery<Canon>({
    queryKey: ["series", sid, "canon"],
    queryFn: () => call(api.GET("/api/series/{series_id}/canon", sp(sid))),
  });
}

export function useIssues(sid: string) {
  return useQuery<Issue[]>({
    queryKey: ["series", sid, "issues"],
    queryFn: () => call(api.GET("/api/series/{series_id}/issues", sp(sid))),
  });
}

export function useProjectSeries(pid: string) {
  return useQuery<Series | null>({
    queryKey: ["series", "of", pid],
    queryFn: () => call(api.GET("/api/projects/{project_id}/series", pp(pid))),
  });
}

export function useSeriesActions(sid: string) {
  const inv = useInvalidate("series");
  const m = <A, R>(fn: (a: A) => Promise<R>) => ({ mutationFn: fn, onSuccess: inv });
  return {
    addBook: useMutation(
      m((project_id: string) =>
        call(api.POST("/api/series/{series_id}/books", { ...sp(sid), body: { project_id } })),
      ),
    ),
    removeBook: useMutation(
      m((project_id: string) =>
        call(
          api.DELETE("/api/series/{series_id}/books/{project_id}", {
            params: { path: { series_id: sid, project_id } },
          }),
        ),
      ),
    ),
    addEntity: useMutation(
      m((body: Schemas["EntityIn"]) =>
        call(api.POST("/api/series/{series_id}/entities", { ...sp(sid), body })),
      ),
    ),
    patchEntity: useMutation(
      m(({ id, body }: { id: string; body: Schemas["EntityPatch"] }) =>
        call(
          api.PATCH("/api/series/{series_id}/entities/{entity_id}", {
            params: { path: { series_id: sid, entity_id: id } },
            body,
          }),
        ),
      ),
    ),
    addFact: useMutation(
      m((body: Schemas["CanonFactIn"]) =>
        call(api.POST("/api/series/{series_id}/facts", { ...sp(sid), body })),
      ),
    ),
    patchFact: useMutation(
      m(({ id, body }: { id: string; body: Schemas["CanonFactPatch"] }) =>
        call(
          api.PATCH("/api/series/{series_id}/facts/{fact_id}", {
            params: { path: { series_id: sid, fact_id: id } },
            body,
          }),
        ),
      ),
    ),
    addRelationship: useMutation(
      m((body: Schemas["RelationshipIn"]) =>
        call(api.POST("/api/series/{series_id}/relationships", { ...sp(sid), body })),
      ),
    ),
    patchRelationship: useMutation(
      m(({ id, body }: { id: string; body: Schemas["RelationshipPatch"] }) =>
        call(
          api.PATCH("/api/series/{series_id}/relationships/{rel_id}", {
            params: { path: { series_id: sid, rel_id: id } },
            body,
          }),
        ),
      ),
    ),
    importNotes: useMutation(
      m((project_id: string) =>
        call(
          api.POST("/api/series/{series_id}/import-notes/{project_id}", {
            params: { path: { series_id: sid, project_id } },
          }),
        ),
      ),
    ),
    review: useMutation(
      m((project_id: string | null) =>
        call(api.POST("/api/series/{series_id}/review", { ...sp(sid), body: { project_id } })),
      ),
    ),
    resolve: useMutation(
      m(({ id, action, note }: { id: string; action: ResolveAction; note?: string }) =>
        call(
          api.POST("/api/series/{series_id}/issues/{issue_id}/resolve", {
            params: { path: { series_id: sid, issue_id: id } },
            body: { action, note: note || null },
          }),
        ),
      ),
    ),
  };
}

export function useCreateSeries() {
  const inv = useInvalidate("series");
  return useMutation({
    mutationFn: (body: Schemas["SeriesIn"]) => call(api.POST("/api/series", { body })),
    onSuccess: inv,
  });
}

// ---------- voice ----------

export function useProjectVoice(pid: string) {
  return useQuery<ProjectVoice>({
    queryKey: ["voice", "project", pid],
    queryFn: () => call(api.GET("/api/projects/{project_id}/voice", pp(pid))),
  });
}

export function useSetProjectVoice(pid: string) {
  const inv = useInvalidate("voice");
  return useMutation({
    mutationFn: (author_profile_id: string | null) =>
      call(api.PUT("/api/projects/{project_id}/voice", { ...pp(pid), body: { author_profile_id } })),
    onSuccess: inv,
  });
}

export function useSetPenName() {
  const inv = useInvalidate("voice");
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas["PenNameIn"] }) =>
      call(
        api.PUT("/api/voice/profiles/{profile_id}/pen-name", { params: { path: { profile_id: id } }, body }),
      ),
    onSuccess: inv,
  });
}

// ---------- translation ----------

export function useEditions(pid: string) {
  return useQuery<Edition[]>({
    queryKey: ["editions", pid],
    queryFn: async () =>
      (await call(api.GET("/api/projects/{project_id}/editions", pp(pid)))) as unknown as Edition[],
  });
}

export function useChapterLinks(pid: string, cid: string) {
  return useQuery<ChapterLinks>({
    queryKey: ["editions", "links", pid, cid],
    queryFn: async () =>
      (await call(
        api.GET("/api/projects/{project_id}/chapters/{chapter_id}/translations", {
          params: { path: { project_id: pid, chapter_id: cid } },
        }),
      )) as unknown as ChapterLinks,
  });
}

export function useEditionActions(pid: string) {
  const inv = useInvalidate("editions", "jobs", "projects");
  return {
    create: useMutation({
      mutationFn: (body: Schemas["EditionIn"]) =>
        call(api.POST("/api/projects/{project_id}/editions", { ...pp(pid), body })),
      onSuccess: inv,
    }),
    terms: useMutation({
      mutationFn: ({ id, term_map }: { id: string; term_map: Record<string, string> }) =>
        call(
          api.PUT("/api/projects/{project_id}/editions/{edition_id}/terms", {
            params: { path: { project_id: pid, edition_id: id } },
            body: { term_map },
          }),
        ),
      onSuccess: inv,
    }),
    translate: useMutation({
      mutationFn: ({ id, body }: { id: string; body: Schemas["TranslateIn"] }) =>
        call(
          api.POST("/api/projects/{project_id}/editions/{edition_id}/translate", {
            params: { path: { project_id: pid, edition_id: id } },
            body,
          }),
        ),
      onSuccess: inv,
    }),
    reviewIssue: useMutation({
      mutationFn: ({
        id,
        chapterId,
        index,
        state,
      }: {
        id: string;
        chapterId: string;
        index: number;
        state: Schemas["IssueStateIn"]["state"];
      }) =>
        call(
          api.PUT("/api/projects/{project_id}/editions/{edition_id}/chapters/{chapter_id}/issues/{index}", {
            params: { path: { project_id: pid, edition_id: id, chapter_id: chapterId, index } },
            body: { state },
          }),
        ),
      onSuccess: inv,
    }),
  };
}

// ---------- narration and recordings ----------

export function useMediaStatus() {
  return useQuery<MediaStatus>({
    queryKey: ["media", "status"],
    queryFn: () => call(api.GET("/api/media/status")),
  });
}

export function useNarration(pid: string) {
  return useQuery<Narration>({
    queryKey: ["media", "narration", pid],
    queryFn: () => call(api.GET("/api/projects/{project_id}/narration", pp(pid))),
  });
}

export interface ScriptItem {
  id: string;
  ordinal: number;
  text: string;
  block_ids: string[];
  notes: string[];
  status: string;
  provider: string | null;
  voice: string | null;
  duration_ms: number | null;
  cost: string | null;
  error: string | null;
  has_audio: boolean;
}

export interface ChapterNarration {
  chapter_id: string;
  title: string;
  revision_no: number;
  chunks: number;
  done: number;
  failed: number;
  duration_ms: number;
  chars: number;
  notes: number;
  older_revision_audio: boolean;
  cost: string | null;
  items?: ScriptItem[];
}

export function useScript(pid: string, cid: string | null) {
  return useQuery({
    queryKey: ["media", "script", pid, cid],
    queryFn: async () =>
      (await call(
        api.GET("/api/projects/{project_id}/narration/chapters/{chapter_id}", {
          params: { path: { project_id: pid, chapter_id: cid ?? "" } },
        }),
      )) as unknown as ChapterNarration,
    enabled: !!cid,
  });
}

export function useNarrationActions(pid: string) {
  const inv = useInvalidate("media");
  const ch = (cid: string) => ({ params: { path: { project_id: pid, chapter_id: cid } } });
  return {
    settings: useMutation({
      mutationFn: (body: NarrationSettings) =>
        call(api.PUT("/api/projects/{project_id}/narration/settings", { ...pp(pid), body })),
      onSuccess: inv,
    }),
    prepare: useMutation({
      mutationFn: (cid: string) =>
        call(api.POST("/api/projects/{project_id}/narration/chapters/{chapter_id}/prepare", ch(cid))),
      onSuccess: inv,
    }),
    synthesize: useMutation({
      mutationFn: (cid: string) =>
        call(
          api.POST("/api/projects/{project_id}/narration/chapters/{chapter_id}/synthesize", {
            params: { path: { project_id: pid, chapter_id: cid }, query: { limit: 10 } },
          }),
        ),
      onSuccess: inv,
    }),
    exportAudio: useMutation({
      mutationFn: () =>
        runTask<Schemas["AudioExportOut"]>(
          call(api.POST("/api/projects/{project_id}/narration/export-task", pp(pid))),
        ),
      onSuccess: inv,
    }),
  };
}

export const partAudioUrl = (pid: string, chunkId: string) =>
  `/api/projects/${pid}/narration/parts/${chunkId}/audio`;
export const audioExportUrl = (pid: string, name: string) =>
  `/api/projects/${pid}/narration/exports/${encodeURIComponent(name)}`;
export const recordingAudioUrl = (pid: string, rid: string) => `/api/projects/${pid}/recordings/${rid}/audio`;

export function useRecordings(pid: string) {
  return useQuery<Recording[]>({
    queryKey: ["media", "recordings", pid],
    queryFn: () => call(api.GET("/api/projects/{project_id}/recordings", pp(pid))),
  });
}

export function useRecordingActions(pid: string) {
  const inv = useInvalidate("media", "knowledge");
  const rp = (rid: string) => ({ params: { path: { project_id: pid, recording_id: rid } } });
  return {
    upload: useMutation({
      mutationFn: (v: { file: File; title: string; rights_confirmed: boolean; rights_note: string }) =>
        upload<Recording>(`/api/projects/${pid}/recordings`, v.file, v.file.name, {
          title: v.title,
          rights_confirmed: v.rights_confirmed ? "true" : "false",
          rights_note: v.rights_note,
        }),
      onSuccess: inv,
    }),
    transcribe: useMutation({
      mutationFn: ({ rid, body }: { rid: string; body: Schemas["TranscribeIn"] }) =>
        call(
          api.POST("/api/projects/{project_id}/recordings/{recording_id}/transcribe", { ...rp(rid), body }),
        ),
      onSuccess: inv,
    }),
    speaker: useMutation({
      mutationFn: ({
        rid,
        segmentId,
        body,
      }: {
        rid: string;
        segmentId: string;
        body: Schemas["SpeakerIn"];
      }) =>
        call(
          api.PUT("/api/projects/{project_id}/recordings/{recording_id}/segments/{segment_id}/speaker", {
            params: { path: { project_id: pid, recording_id: rid, segment_id: segmentId } },
            body,
          }),
        ),
      onSuccess: inv,
    }),
    quote: useMutation({
      mutationFn: ({ rid, body }: { rid: string; body: Schemas["QuoteIn"] }) =>
        call(api.POST("/api/projects/{project_id}/recordings/{recording_id}/quotes", { ...rp(rid), body })),
      onSuccess: inv,
    }),
  };
}

export function ms(n: number | null | undefined): string {
  if (n == null) return "—";
  const s = Math.floor(n / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
