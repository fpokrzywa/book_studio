import { useId, useState } from "react";
import { Link, useParams } from "react-router";
import {
  audioExportUrl,
  ms,
  partAudioUrl,
  recordingAudioUrl,
  useMediaStatus,
  useNarration,
  useNarrationActions,
  useRecordingActions,
  useRecordings,
  useScript,
  type ChapterNarration,
  type Narration,
  type NarrationSettings,
  type Recording,
} from "../../api/advanced";
import { useProviders } from "../../api/ai";
import { useProject } from "../../api/hooks";
import { useAnnounce } from "../../components/Announcer";
import { PageHeader, usePageTitle } from "../../components/Misc";
import { EmptyState, ErrorState, InlineError, Loading } from "../../components/States";

// ---------- narration ----------

export function NarrationPage() {
  const { projectId = "" } = useParams();
  const project = useProject(projectId);
  const narration = useNarration(projectId);
  usePageTitle("Narration");
  if (narration.isError)
    return <ErrorState error={narration.error} onRetry={() => void narration.refetch()} />;
  if (!project.data || !narration.data) return <Loading label="Loading narration" />;
  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to={`/projects/${projectId}`}>{project.data.title}</Link>
      </nav>
      <PageHeader
        title="Narration"
        intro="Turn the book into speech-ready parts, then make audio with a speech engine you choose."
      />
      <div className="stack">
        <p className="hint">{narration.data.note}</p>
        <NarrationSettingsPanel
          key={JSON.stringify(narration.data.settings)}
          projectId={projectId}
          data={narration.data}
        />
        <NarrationChapters projectId={projectId} data={narration.data} />
      </div>
    </>
  );
}

function NarrationSettingsPanel({ projectId, data }: { projectId: string; data: Narration }) {
  const id = useId();
  const actions = useNarrationActions(projectId);
  const providers = useProviders();
  const announce = useAnnounce();
  const [s, setS] = useState<NarrationSettings>(data.settings as NarrationSettings);
  const engines = data.providers as {
    kind: string;
    label: string;
    local: boolean;
    available: boolean;
    reason: string;
  }[];
  const openaiProviders = (providers.data ?? []).filter((p) => p.kind === "openai");
  return (
    <section className="panel" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>Speech engine</h2>
      <ul className="engine-list">
        {engines.map((e) => (
          <li key={e.kind} data-available={e.available}>
            <strong>{e.label}</strong>: {e.available ? "ready" : e.reason}
          </li>
        ))}
      </ul>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          actions.settings.mutate(s, { onSuccess: () => announce("Narration settings saved") });
        }}
      >
        <label className="inline-check">
          <input
            type="checkbox"
            checked={!!s.enabled}
            onChange={(e) => setS({ ...s, enabled: e.target.checked })}
          />
          Make audio for this book
        </label>
        <div className="form-row adv-row">
          <div className="field">
            <label htmlFor={`${id}-eng`}>Engine</label>
            <select
              id={`${id}-eng`}
              value={s.provider ?? ""}
              onChange={(e) => setS({ ...s, provider: e.target.value as NarrationSettings["provider"] })}
            >
              <option value="">None</option>
              {engines.map((e) => (
                <option key={e.kind} value={e.kind}>
                  {e.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor={`${id}-voice`}>Voice</label>
            <input
              id={`${id}-voice`}
              value={s.voice ?? ""}
              onChange={(e) => setS({ ...s, voice: e.target.value })}
              placeholder={s.provider === "openai" ? "marin" : s.provider === "espeak" ? "en-gb" : ""}
            />
          </div>
          {s.provider === "openai" ? (
            <>
              <div className="field">
                <label htmlFor={`${id}-oai`}>OpenAI provider</label>
                <select
                  id={`${id}-oai`}
                  value={s.openai_provider_id ?? ""}
                  onChange={(e) => setS({ ...s, openai_provider_id: e.target.value || null })}
                >
                  <option value="">Choose…</option>
                  {openaiProviders.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor={`${id}-model`}>Speech model</label>
                <input
                  id={`${id}-model`}
                  value={s.model ?? ""}
                  placeholder="gpt-4o-mini-tts"
                  onChange={(e) => setS({ ...s, model: e.target.value })}
                />
              </div>
            </>
          ) : null}
        </div>
        <div className="form-row adv-row">
          <div className="field">
            <label htmlFor={`${id}-price`}>
              Price per million characters (from the provider's price list)
            </label>
            <input
              id={`${id}-price`}
              inputMode="decimal"
              value={s.price_per_million_chars ?? ""}
              onChange={(e) => setS({ ...s, price_per_million_chars: e.target.value })}
              aria-describedby={`${id}-price-hint`}
            />
            <p className="hint" id={`${id}-price-hint`}>
              Leave empty if you don't know it: the cost is then shown as unknown, never guessed. Engines on
              this computer cost nothing per character.
            </p>
          </div>
          <div className="field">
            <label htmlFor={`${id}-cur`}>Currency</label>
            <input
              id={`${id}-cur`}
              value={s.currency ?? ""}
              maxLength={3}
              placeholder="USD"
              onChange={(e) => setS({ ...s, currency: e.target.value.toUpperCase() })}
            />
          </div>
          <div className="field">
            <label htmlFor={`${id}-max`}>Longest part (characters)</label>
            <input
              id={`${id}-max`}
              type="number"
              min={200}
              max={4000}
              value={s.max_chunk_chars ?? 1500}
              onChange={(e) => setS({ ...s, max_chunk_chars: Number(e.target.value) })}
            />
          </div>
        </div>
        <button type="submit" className="btn btn-primary" disabled={actions.settings.isPending}>
          Save
        </button>
        {actions.settings.error ? <InlineError error={actions.settings.error} /> : null}
      </form>
    </section>
  );
}

function NarrationChapters({ projectId, data }: { projectId: string; data: Narration }) {
  const id = useId();
  const actions = useNarrationActions(projectId);
  const announce = useAnnounce();
  const [open, setOpen] = useState<string | null>(null);
  const chapters = data.chapters as unknown as ChapterNarration[];
  const ready = chapters.some((c) => c.chunks > 0 && c.done === c.chunks);
  const error = actions.prepare.error ?? actions.synthesize.error ?? actions.exportAudio.error;
  return (
    <section className="panel" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>Chapters</h2>
      {error ? <InlineError error={error} /> : null}
      <table className="data-table">
        <caption className="visually-hidden">Narration progress by chapter</caption>
        <thead>
          <tr>
            <th scope="col">Chapter</th>
            <th scope="col">Audio parts made</th>
            <th scope="col">Length</th>
            <th scope="col">Cost</th>
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          {chapters.map((c) => (
            <tr key={c.chapter_id}>
              <th scope="row">
                {c.title} <span className="muted">(revision {c.revision_no})</span>
                {c.older_revision_audio ? (
                  <div className="muted">Audio exists for an older revision only.</div>
                ) : null}
              </th>
              <td>
                {c.chunks ? (
                  <>
                    <progress max={c.chunks} value={c.done} aria-label={`${c.done} of ${c.chunks} parts`} />{" "}
                    {c.done} of {c.chunks}
                    {c.failed ? <span className="tag"> {c.failed} failed</span> : null}
                  </>
                ) : (
                  <span className="muted">Script not prepared</span>
                )}
              </td>
              <td>{c.done ? ms(c.duration_ms) : "—"}</td>
              <td>{c.cost ?? "—"}</td>
              <td className="row-actions">
                {!c.chunks ? (
                  <button
                    type="button"
                    className="btn btn-small"
                    onClick={() => actions.prepare.mutate(c.chapter_id)}
                  >
                    Prepare script
                  </button>
                ) : (
                  <>
                    <button
                      type="button"
                      className="btn btn-small"
                      onClick={() => setOpen(open === c.chapter_id ? null : c.chapter_id)}
                    >
                      {open === c.chapter_id ? "Hide script" : "Show script"}
                    </button>
                    {c.done < c.chunks ? (
                      <button
                        type="button"
                        className="btn btn-small"
                        disabled={actions.synthesize.isPending}
                        onClick={() =>
                          actions.synthesize.mutate(c.chapter_id, { onSuccess: (r) => announce(r.message) })
                        }
                      >
                        {actions.synthesize.isPending ? "Making audio…" : "Make audio for the next parts"}
                      </button>
                    ) : null}
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {open ? <ScriptView projectId={projectId} chapterId={open} /> : null}
      <div className="page-actions">
        <button
          type="button"
          className="btn btn-primary"
          disabled={!ready || actions.exportAudio.isPending}
          onClick={() => actions.exportAudio.mutate()}
        >
          Export audio
        </button>
        {!ready ? (
          <span className="muted">Export is ready once a chapter has audio for every part.</span>
        ) : null}
      </div>
      {actions.exportAudio.data ? (
        <div className="notes">
          <p>
            <a href={audioExportUrl(projectId, actions.exportAudio.data.file_name)} download>
              Download {actions.exportAudio.data.file_name}
            </a>{" "}
            ({Math.round(actions.exportAudio.data.bytes / 1024)} KB,{" "}
            {actions.exportAudio.data.chapters.length} chapter(s))
          </p>
          <pre className="notes-text">{actions.exportAudio.data.notes}</pre>
        </div>
      ) : null}
    </section>
  );
}

function ScriptView({ projectId, chapterId }: { projectId: string; chapterId: string }) {
  const id = useId();
  const script = useScript(projectId, chapterId);
  if (!script.data) return <Loading label="Loading the script" />;
  return (
    <section aria-labelledby={`${id}-h`} className="script">
      <h3 id={`${id}-h`}>Script for “{script.data.title}”</h3>
      <ol>
        {(script.data.items ?? []).map((it) => (
          <li key={it.id} data-status={it.status}>
            <p>{it.text}</p>
            {it.notes.length ? <p className="muted">{it.notes.join(" ")}</p> : null}
            {it.has_audio ? (
              // Audio-only: the text above is the transcript (WCAG 1.2.1); captions are for video.
              // eslint-disable-next-line jsx-a11y/media-has-caption
              <audio
                controls
                preload="none"
                src={partAudioUrl(projectId, it.id)}
                aria-label={`Part ${it.ordinal}`}
              />
            ) : it.error ? (
              <p className="inline-error">{it.error}</p>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}

// ---------- recordings ----------

export function RecordingsPage() {
  const { projectId = "" } = useParams();
  const id = useId();
  const project = useProject(projectId);
  const recs = useRecordings(projectId);
  const actions = useRecordingActions(projectId);
  const announce = useAnnounce();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [rights, setRights] = useState(false);
  const [note, setNote] = useState("");
  usePageTitle("Recorded interviews");
  if (recs.isError) return <ErrorState error={recs.error} onRetry={() => void recs.refetch()} />;
  if (!project.data || !recs.data) return <Loading label="Loading recordings" />;
  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to={`/projects/${projectId}`}>{project.data.title}</Link>
      </nav>
      <PageHeader
        title="Recorded interviews"
        intro="Import audio you own or have permission to use, transcribe it with an engine you choose, correct who said what, and keep chosen quotations as sources. Timestamps stay linked to the audio."
      />
      <div className="stack">
        <section className="panel" aria-labelledby={`${id}-up`}>
          <h2 id={`${id}-up`}>Import a recording</h2>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (!file) return;
              actions.upload.mutate(
                { file, title, rights_confirmed: rights, rights_note: note },
                {
                  onSuccess: (r) => (
                    announce(`Imported “${r.title}”`),
                    setFile(null),
                    setTitle(""),
                    setRights(false)
                  ),
                },
              );
            }}
          >
            <div className="form-row adv-row">
              <div className="field">
                <label htmlFor={`${id}-file`}>Audio file (WAV, MP3, M4A, FLAC, OGG or WebM)</label>
                <input
                  id={`${id}-file`}
                  type="file"
                  accept="audio/*"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
              </div>
              <div className="field">
                <label htmlFor={`${id}-title`}>Title</label>
                <input
                  id={`${id}-title`}
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  maxLength={200}
                />
              </div>
            </div>
            <label className="inline-check">
              <input type="checkbox" checked={rights} onChange={(e) => setRights(e.target.checked)} />I own
              this recording, or everyone speaking agreed to its use in this book
            </label>
            <div className="field">
              <label htmlFor={`${id}-note`}>How you have the rights (optional)</label>
              <input
                id={`${id}-note`}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Recorded with written consent, March 2026"
              />
            </div>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={!file || !rights || actions.upload.isPending}
            >
              Import
            </button>
            {actions.upload.error ? <InlineError error={actions.upload.error} /> : null}
          </form>
        </section>
        {recs.data.length ? (
          recs.data.map((r) => <RecordingPanel key={r.id} projectId={projectId} rec={r} />)
        ) : (
          <EmptyState title="No recordings yet">Import an interview above.</EmptyState>
        )}
      </div>
    </>
  );
}

function RecordingPanel({ projectId, rec: r }: { projectId: string; rec: Recording }) {
  const id = useId();
  const status = useMediaStatus();
  const providers = useProviders();
  const actions = useRecordingActions(projectId);
  const announce = useAnnounce();
  const engines = (status.data?.transcription ?? []) as {
    kind: string;
    label: string;
    available: boolean;
    reason: string;
  }[];
  const [engine, setEngine] = useState("");
  const [model, setModel] = useState("");
  const [oai, setOai] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const segs = r.segments as {
    id: string;
    ordinal: number;
    start_ms: number;
    end_ms: number;
    speaker: string;
    text: string;
    source_id: string | null;
  }[];
  const error = actions.transcribe.error ?? actions.speaker.error ?? actions.quote.error;
  return (
    <section className="panel" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>{r.title}</h2>
      <p className="muted">
        {r.mime}, {ms(r.duration_ms)}. Rights: {r.rights_note}
      </p>
      {/* Audio-only: the transcript below is its text alternative (WCAG 1.2.1). */}
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <audio
        controls
        preload="none"
        src={recordingAudioUrl(projectId, r.id)}
        aria-label={`Recording ${r.title}`}
      />
      {error ? <InlineError error={error} /> : null}
      {r.status === "failed" && r.error ? <p className="inline-error">{r.error}</p> : null}
      {!segs.some((g) => g.source_id) ? (
        <form
          className="form-row adv-row"
          onSubmit={(e) => {
            e.preventDefault();
            actions.transcribe.mutate(
              {
                rid: r.id,
                body: {
                  provider: engine as "mock" | "whisper_cli" | "openai",
                  model,
                  openai_provider_id: oai || null,
                  language: "",
                },
              },
              { onSuccess: (x) => announce(`Transcribed: ${x.segments.length} segment(s)`) },
            );
          }}
        >
          <div className="field">
            <label htmlFor={`${id}-eng`}>Transcription engine</label>
            <select id={`${id}-eng`} value={engine} onChange={(e) => setEngine(e.target.value)}>
              <option value="">Choose…</option>
              {engines.map((e) => (
                <option key={e.kind} value={e.kind} disabled={!e.available && e.kind !== "openai"}>
                  {e.label}
                  {e.available ? "" : " (not available)"}
                </option>
              ))}
            </select>
            {engine && !engines.find((e) => e.kind === engine)?.available ? (
              <p className="hint">{engines.find((e) => e.kind === engine)?.reason}</p>
            ) : null}
          </div>
          {engine === "openai" ? (
            <>
              <div className="field">
                <label htmlFor={`${id}-oai`}>OpenAI provider</label>
                <select id={`${id}-oai`} value={oai} onChange={(e) => setOai(e.target.value)}>
                  <option value="">Choose…</option>
                  {(providers.data ?? [])
                    .filter((p) => p.kind === "openai")
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.label}
                      </option>
                    ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor={`${id}-model`}>Model</label>
                <select id={`${id}-model`} value={model} onChange={(e) => setModel(e.target.value)}>
                  <option value="whisper-1">whisper-1 (timestamps)</option>
                  <option value="gpt-4o-transcribe-diarize">
                    gpt-4o-transcribe-diarize (timestamps and speakers)
                  </option>
                </select>
              </div>
            </>
          ) : null}
          <button type="submit" className="btn" disabled={!engine || actions.transcribe.isPending}>
            {actions.transcribe.isPending
              ? "Transcribing…"
              : r.status === "transcribed"
                ? "Transcribe again"
                : "Transcribe"}
          </button>
        </form>
      ) : null}
      {segs.length ? (
        <>
          <h3>Transcript</h3>
          <p className="hint">
            The words and times are kept exactly as the engine returned them. Correct speaker names here; tick
            segments to keep them as a quotation source.
          </p>
          <ol className="transcript">
            {segs.map((g) => (
              <Segment
                key={g.id}
                g={g}
                picked={picked.includes(g.id)}
                onPick={(on) => setPicked(on ? [...picked, g.id] : picked.filter((x) => x !== g.id))}
                onSpeaker={(speaker, all) =>
                  actions.speaker.mutate({
                    rid: r.id,
                    segmentId: g.id,
                    body: { speaker, all_with_label: all },
                  })
                }
              />
            ))}
          </ol>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!picked.length || actions.quote.isPending}
            onClick={() =>
              actions.quote.mutate(
                { rid: r.id, body: { segment_ids: picked, title: null } },
                { onSuccess: () => (announce("Quotation saved as a source"), setPicked([])) },
              )
            }
          >
            Keep {picked.length || ""} selected segment{picked.length === 1 ? "" : "s"} as a source
          </button>
        </>
      ) : null}
    </section>
  );
}

function Segment({
  g,
  picked,
  onPick,
  onSpeaker,
}: {
  g: {
    id: string;
    start_ms: number;
    end_ms: number;
    speaker: string;
    text: string;
    source_id: string | null;
  };
  picked: boolean;
  onPick: (on: boolean) => void;
  onSpeaker: (speaker: string, all: boolean) => void;
}) {
  const id = useId();
  const [name, setName] = useState(g.speaker);
  return (
    <li>
      <label className="inline-check">
        <input type="checkbox" checked={picked} onChange={(e) => onPick(e.target.checked)} />
        <span className="muted">
          {ms(g.start_ms)}–{ms(g.end_ms)}
        </span>
      </label>{" "}
      <strong>{g.speaker}</strong>: {g.text}
      {g.source_id ? <span className="tag"> in sources</span> : null}
      <details>
        <summary>Correct the speaker</summary>
        <form
          className="form-row compact"
          onSubmit={(e) => {
            e.preventDefault();
            onSpeaker(name.trim(), (e.nativeEvent as SubmitEvent).submitter?.getAttribute("value") === "all");
          }}
        >
          <div className="field">
            <label htmlFor={`${id}-sp`}>Speaker</label>
            <input id={`${id}-sp`} value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <button type="submit" className="btn btn-small" value="one" disabled={!name.trim()}>
            This segment
          </button>
          <button type="submit" className="btn btn-small" value="all" disabled={!name.trim()}>
            Every “{g.speaker}” segment
          </button>
        </form>
      </details>
    </li>
  );
}
