import { useId, useState } from "react";
import { Link } from "react-router";
import {
  STATUS_TEXT,
  TITLE_ORIGIN,
  useSearch,
  useSourceActions,
  type SearchHit,
  type Source,
  type SourceImport,
} from "../../api/knowledge";
import { useAnnounce } from "../../components/Announcer";
import { ConfirmDialog } from "../../components/Dialog";
import { InlineError, Loading } from "../../components/States";
import { words } from "../../lib/format";

const KINDS = ".md,.markdown,.txt,.html,.htm,.docx,.pdf";

/** A search snippet: source text shown as text, with matched words marked. Never HTML from the source. */
export function Snippet({ parts }: { parts: SearchHit["snippet"] }) {
  return (
    <p className="snippet">
      {parts.map((p, i) => (p.hit ? <mark key={i}>{p.text}</mark> : <span key={i}>{p.text}</span>))}
    </p>
  );
}

export function passageLink(sourceId: string, chunkId?: string | null): string {
  return `/knowledge/sources/${sourceId}${chunkId ? `?passage=${chunkId}` : ""}`;
}

export function ImportSourceForm({
  label,
  onImport,
  pending,
  error,
}: {
  label: string;
  onImport: (file: File, allowDuplicate: boolean) => Promise<SourceImport>;
  pending: boolean;
  error: unknown;
}) {
  const id = useId();
  const announce = useAnnounce();
  const [file, setFile] = useState<File | null>(null);
  const [dup, setDup] = useState<SourceImport["duplicate"] | null>(null);
  const [inputKey, setInputKey] = useState(0);
  const go = async (allowDuplicate: boolean) => {
    if (!file) return;
    const res = await onImport(file, allowDuplicate);
    if (res.duplicate) {
      setDup(res.duplicate);
      return;
    }
    setDup(null);
    setFile(null);
    setInputKey((k) => k + 1);
    const s = res.source;
    announce(
      s?.status === "indexed"
        ? `Added “${s.title}”. It is searchable now.`
        : `Added “${s?.title}”, but it could not be read.`,
    );
  };
  return (
    <form
      className="form import-source"
      aria-labelledby={`${id}-h`}
      onSubmit={(e) => {
        e.preventDefault();
        void go(false).catch(() => undefined);
      }}
    >
      <h3 id={`${id}-h`}>{label}</h3>
      <div className="field">
        <label htmlFor={`${id}-file`}>File</label>
        <input
          key={inputKey}
          id={`${id}-file`}
          type="file"
          accept={KINDS}
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setDup(null);
          }}
        />
        <p className="hint">
          Markdown, text, HTML, Word (.docx) or text-based PDF. The original file is kept unchanged; its text
          is split into passages you can search and cite.
        </p>
      </div>
      {dup ? (
        <div className="banner" role="status">
          <span>
            {dup.reason === "same_file"
              ? "This exact file is already here"
              : "A source with the same text is already here"}
            : “{dup.title}”.
          </span>
          {dup.reason === "same_text" ? (
            <button
              type="button"
              className="btn btn-small"
              onClick={() => void go(true).catch(() => undefined)}
            >
              Add it anyway
            </button>
          ) : null}
        </div>
      ) : null}
      {error ? <InlineError error={error} /> : null}
      <div className="page-actions">
        <button type="submit" className="btn btn-primary" disabled={!file || pending}>
          {pending ? "Adding…" : "Add source"}
        </button>
      </div>
    </form>
  );
}

export function SourceList({ sources, readOnly = false }: { sources: Source[]; readOnly?: boolean }) {
  const actions = useSourceActions();
  const announce = useAnnounce();
  const [removing, setRemoving] = useState<Source | null>(null);
  const error = actions.patch.error ?? actions.remove.error ?? actions.reindex.error;
  if (sources.length === 0) return <p className="muted">No sources yet.</p>;
  return (
    <>
      {error ? <InlineError error={error} /> : null}
      <ul className="source-list">
        {sources.map((s) => (
          <li key={s.id} className="source-item" data-enabled={s.enabled} data-status={s.status}>
            <div className="source-main">
              <Link to={passageLink(s.id)} className="source-title">
                {s.title}
              </Link>
              <span className="muted">
                {" "}
                @{s.citation_key} · {s.kind.toUpperCase()} · {STATUS_TEXT[s.status]}
                {s.status === "indexed" ? ` · ${s.chunk_count} passages, ${words(s.word_count)}` : ""}
                {s.page_count ? ` · ${s.page_count} pages` : ""}
              </span>
              {s.error ? <p className="job-error">{s.error}</p> : null}
              {s.tags.length ? (
                <ul className="tags" aria-label="Tags">
                  {s.tags.map((t) => (
                    <li key={t} className="tag">
                      {t}
                    </li>
                  ))}
                </ul>
              ) : null}
              <p className="hint">Title {TITLE_ORIGIN[s.title_origin] ?? s.title_origin}.</p>
            </div>
            {!readOnly ? (
              <div className="page-actions">
                <label className="inline-check">
                  <input
                    type="checkbox"
                    checked={s.enabled}
                    disabled={s.status !== "indexed" || actions.patch.isPending}
                    onChange={(e) =>
                      actions.patch.mutate(
                        { id: s.id, enabled: e.target.checked },
                        {
                          onSuccess: (r) =>
                            announce(
                              r.enabled
                                ? `“${r.title}” can be used by AI`
                                : `“${r.title}” will not be used by AI`,
                            ),
                        },
                      )
                    }
                  />
                  Use for AI
                </label>
                <button type="button" className="btn btn-small" onClick={() => actions.reindex.mutate(s.id)}>
                  Re-read file
                </button>
                <button type="button" className="btn btn-small btn-danger" onClick={() => setRemoving(s)}>
                  Remove
                </button>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
      <ConfirmDialog
        isOpen={removing !== null}
        title={`Remove “${removing?.title ?? ""}”?`}
        body="It disappears from search and is never sent to AI again. Quotes already saved in the evidence ledger are kept and marked as from a removed source. The original file stays in your workspace."
        confirmLabel="Remove source"
        danger
        busy={actions.remove.isPending}
        onCancel={() => setRemoving(null)}
        onConfirm={() =>
          removing &&
          actions.remove.mutate(removing.id, {
            onSuccess: () => {
              announce(`Removed “${removing.title}”`);
              setRemoving(null);
            },
          })
        }
      />
    </>
  );
}

export function SearchPanel({
  scope,
  label,
  onPick,
  pickLabel,
}: {
  scope: { projectId?: string; libraryId?: string };
  label: string;
  onPick?: (hit: SearchHit) => void;
  pickLabel?: string;
}) {
  const id = useId();
  const [draft, setDraft] = useState("");
  const [q, setQ] = useState("");
  const result = useSearch(scope, q);
  return (
    <section className="search-panel" aria-labelledby={`${id}-h`}>
      <h3 id={`${id}-h`}>{label}</h3>
      <form
        role="search"
        className="search-row"
        onSubmit={(e) => {
          e.preventDefault();
          setQ(draft.trim());
        }}
      >
        <label htmlFor={`${id}-q`} className="visually-hidden">
          Search words
        </label>
        <input id={`${id}-q`} type="search" value={draft} onChange={(e) => setDraft(e.target.value)} />
        <button type="submit" className="btn">
          Search
        </button>
      </form>
      {result.isFetching ? <Loading label="Searching" /> : null}
      {result.error ? <InlineError error={result.error} /> : null}
      {result.data ? (
        <div aria-live="polite">
          <p className="hint">
            {result.data.hits.length === 0
              ? `No passages match in ${result.data.searched_sources} source(s).`
              : result.data.mode === "all"
                ? `${result.data.hits.length} passage(s) contain every word.`
                : `No passage contains every word; showing passages with some of them.`}{" "}
            {result.data.semantic_note}
          </p>
          <ol className="hits">
            {result.data.hits.map((h) => (
              <li key={h.chunk_id} className="hit">
                <p className="hit-head">
                  <Link to={passageLink(h.source_id, h.chunk_id)}>{h.source_title}</Link>{" "}
                  <span className="muted">
                    @{h.citation_key}, {h.locator}
                    {h.heading_path ? ` · ${h.heading_path}` : ""}
                  </span>
                </p>
                <Snippet parts={h.snippet} />
                <p className="hint">Why it matched: {h.reasons.join(". ")}.</p>
                {onPick ? (
                  <button type="button" className="btn btn-small" onClick={() => onPick(h)}>
                    {pickLabel ?? "Use this passage"}
                  </button>
                ) : null}
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </section>
  );
}
