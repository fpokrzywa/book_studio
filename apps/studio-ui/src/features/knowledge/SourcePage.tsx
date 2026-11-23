import { useEffect, useId, useState } from "react";
import { useParams, useSearchParams } from "react-router";
import { TITLE_ORIGIN, useSourceActions, useSourceText, type Source } from "../../api/knowledge";
import { useAnnounce } from "../../components/Announcer";
import { PageHeader } from "../../components/Misc";
import { ErrorState, InlineError, Loading } from "../../components/States";

/** Read a source passage by passage. A citation link opens here with the cited passage highlighted. */
export function SourcePage() {
  const { sourceId = "" } = useParams();
  const [params] = useSearchParams();
  const target = params.get("passage");
  const text = useSourceText(sourceId);
  useEffect(() => {
    if (target && text.data) document.getElementById(`passage-${target}`)?.focus();
  }, [target, text.data]);
  if (text.isError) return <ErrorState error={text.error} onRetry={() => void text.refetch()} />;
  if (!text.data) return <Loading label="Opening the source" />;
  const s = text.data.source;
  return (
    <>
      <PageHeader
        title={s.title}
        intro={`Cite as [@${s.citation_key}]. ${s.removed_at ? "This source was removed: it is no longer searched or sent to AI." : s.enabled ? "Available to AI." : "Not used by AI (turned off)."}`}
      />
      {target && !text.data.chunks.some((c) => c.id === target) ? (
        <div className="banner" role="note">
          The cited passage is no longer in this source (it was removed or re-read). The evidence ledger keeps
          the quoted text.
        </div>
      ) : null}
      <div className="two-col">
        <section aria-label="Passages" className="passages">
          {text.data.chunks.length === 0 ? <p className="muted">No passages.</p> : null}
          {text.data.chunks.map((c) => (
            <article
              key={c.id}
              id={`passage-${c.id}`}
              tabIndex={-1}
              className="passage"
              data-target={c.id === target}
              aria-label={`${c.locator}${c.id === target ? ", cited passage" : ""}`}
            >
              <p className="passage-where">
                {c.locator}
                {c.heading_path ? ` · ${c.heading_path}` : ""}
                {c.id === target ? <strong> · cited passage</strong> : null}
              </p>
              {c.text.split("\n\n").map((para, i) => (
                <p key={i}>{para}</p>
              ))}
            </article>
          ))}
        </section>
        <SourceDetails source={s} />
      </div>
    </>
  );
}

function SourceDetails({ source: s }: { source: Source }) {
  const id = useId();
  const announce = useAnnounce();
  const actions = useSourceActions();
  const [form, setForm] = useState({
    title: s.title,
    authors: s.authors.join("; "),
    year: s.year ?? "",
    publisher: s.publisher ?? "",
    url: s.url ?? "",
    doi: s.doi ?? "",
    tags: s.tags.join(", "),
  });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [k]: e.target.value });
  const removed = !!s.removed_at;
  return (
    <form
      className="form panel"
      aria-labelledby={`${id}-h`}
      onSubmit={(e) => {
        e.preventDefault();
        actions.patch.mutate(
          {
            id: s.id,
            title: form.title.trim(),
            authors: form.authors
              .split(";")
              .map((a) => a.trim())
              .filter(Boolean),
            year: form.year.trim() || null,
            publisher: form.publisher.trim() || null,
            url: form.url.trim() || null,
            doi: form.doi.trim() || null,
            tags: form.tags
              .split(",")
              .map((t) => t.trim())
              .filter(Boolean),
          },
          { onSuccess: () => announce("Source details saved") },
        );
      }}
    >
      <h2 id={`${id}-h`}>Details for the bibliography</h2>
      <p className="hint">
        Only what you enter here is used. Personal Book Studio never guesses an author, year, URL or DOI. The
        title is {TITLE_ORIGIN[s.title_origin] ?? s.title_origin}. The citation key @{s.citation_key} never
        changes.
      </p>
      <fieldset disabled={removed}>
        <legend className="visually-hidden">Source details</legend>
        {(
          [
            ["title", "Title"],
            ["authors", "Authors (separate with ;)"],
            ["year", "Year"],
            ["publisher", "Publisher"],
            ["url", "Web address"],
            ["doi", "DOI"],
            ["tags", "Tags (separate with ,)"],
          ] as const
        ).map(([k, label]) => (
          <div className="field" key={k}>
            <label htmlFor={`${id}-${k}`}>{label}</label>
            <input id={`${id}-${k}`} value={form[k]} onChange={set(k)} />
          </div>
        ))}
      </fieldset>
      <p className="hint">
        File: {s.original_name} ({s.kind.toUpperCase()}), SHA-256 {s.file_sha256.slice(0, 12)}…
      </p>
      {actions.patch.error ? <InlineError error={actions.patch.error} /> : null}
      {!removed ? (
        <div className="page-actions">
          <button type="submit" className="btn btn-primary" disabled={actions.patch.isPending}>
            Save details
          </button>
        </div>
      ) : null}
    </form>
  );
}
