import { useId, useState } from "react";
import { Link, useParams } from "react-router";
import { useChapterLinks, useEditionActions, useEditions, type Edition } from "../../api/advanced";
import { useProviders } from "../../api/ai";
import { useProject } from "../../api/hooks";
import { useAnnounce } from "../../components/Announcer";
import { PageHeader, usePageTitle } from "../../components/Misc";
import { EmptyState, ErrorState, InlineError, Loading } from "../../components/States";

const STATUS: Record<string, string> = {
  not_started: "Not translated",
  requested: "Translating…",
  suggested: "Translation waiting for your review",
  accepted: "Translation accepted",
  rejected: "Translation rejected",
};

/** Translated editions of a book. Each edition is its own linked book; the original is only read. */
export function TranslationsPage() {
  const { projectId = "" } = useParams();
  const id = useId();
  const project = useProject(projectId);
  const editions = useEditions(projectId);
  const actions = useEditionActions(projectId);
  const announce = useAnnounce();
  const [lang, setLang] = useState("");
  const [title, setTitle] = useState("");
  usePageTitle("Translations");
  if (editions.isError) return <ErrorState error={editions.error} onRetry={() => void editions.refetch()} />;
  if (!project.data || !editions.data) return <Loading label="Loading translations" />;
  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to={`/projects/${projectId}`}>{project.data.title}</Link>
      </nav>
      <PageHeader
        title="Translations"
        intro={`Each translation is its own book, linked chapter by chapter to “${project.data.title}” (${project.data.language}). Only approved chapters are translated, and the original is never changed.`}
      />
      <div className="stack">
        <section className="panel" aria-labelledby={`${id}-new`}>
          <h2 id={`${id}-new`}>New translated edition</h2>
          <form
            className="form-row adv-row"
            onSubmit={(e) => {
              e.preventDefault();
              actions.create.mutate(
                { language: lang.trim(), title: title.trim() || null, term_map: {} },
                {
                  onSuccess: (ed) => (
                    announce(`Edition “${ed.target_title}” created`),
                    setLang(""),
                    setTitle("")
                  ),
                },
              );
            }}
          >
            <div className="field">
              <label htmlFor={`${id}-lang`}>Language code</label>
              <input
                id={`${id}-lang`}
                value={lang}
                onChange={(e) => setLang(e.target.value)}
                placeholder="fr, de, es-MX"
                aria-describedby={`${id}-lang-hint`}
              />
              <p className="hint" id={`${id}-lang-hint`}>
                A language tag such as fr (French), de (German) or pt-BR (Brazilian Portuguese).
              </p>
            </div>
            <div className="field">
              <label htmlFor={`${id}-title`}>Title of the edition (optional)</label>
              <input
                id={`${id}-title`}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={300}
              />
            </div>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={!lang.trim() || actions.create.isPending}
            >
              Create edition
            </button>
          </form>
          {actions.create.error ? <InlineError error={actions.create.error} /> : null}
        </section>
        {editions.data.length ? (
          editions.data.map((ed) => <EditionPanel key={ed.id} projectId={projectId} edition={ed} />)
        ) : (
          <EmptyState title="No translations yet">Create an edition above to start.</EmptyState>
        )}
      </div>
    </>
  );
}

function EditionPanel({ projectId, edition: ed }: { projectId: string; edition: Edition }) {
  const id = useId();
  const actions = useEditionActions(projectId);
  const providers = useProviders();
  const announce = useAnnounce();
  const usable = (providers.data ?? []).filter((p) => p.enabled);
  const [prov, setProv] = useState("");
  const [model, setModel] = useState("");
  const [terms, setTerms] = useState(
    Object.entries(ed.term_map)
      .map(([k, v]) => `${k} = ${v}`)
      .join("\n"),
  );
  const chosen = usable.find((p) => p.id === prov);
  const error = actions.translate.error ?? actions.terms.error ?? actions.reviewIssue.error;
  return (
    <section className="panel" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>
        {ed.target_title} <span className="tag">{ed.language}</span>
      </h2>
      <p>
        <Link to={`/projects/${ed.target_project_id}`}>Open this edition</Link>
      </p>
      {error ? <InlineError error={error} /> : null}
      <div className="form-row adv-row">
        <div className="field">
          <label htmlFor={`${id}-p`}>AI provider for translating</label>
          <select id={`${id}-p`} value={prov} onChange={(e) => (setProv(e.target.value), setModel(""))}>
            <option value="">Use the default for “translate” (AI settings)</option>
            {usable.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
                {p.local ? " (on this computer)" : " (cloud)"}
              </option>
            ))}
          </select>
        </div>
        {chosen ? (
          <div className="field">
            <label htmlFor={`${id}-m`}>Model</label>
            <select id={`${id}-m`} value={model} onChange={(e) => setModel(e.target.value)}>
              <option value="">Choose…</option>
              {chosen.models.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.display_name ?? m.name}
                </option>
              ))}
            </select>
          </div>
        ) : null}
      </div>
      <table className="data-table">
        <caption className="visually-hidden">Chapters of {ed.target_title}</caption>
        <thead>
          <tr>
            <th scope="col">Original chapter</th>
            <th scope="col">Translation</th>
            <th scope="col">Status</th>
            <th scope="col">Action</th>
          </tr>
        </thead>
        <tbody>
          {ed.chapters.map((c) => {
            const approved = c.source_status === "approved";
            return (
              <tr key={c.target_chapter_id}>
                <th scope="row">
                  <Link to={`/projects/${ed.source_project_id}/chapters/${c.source_chapter_id}`}>
                    {c.source_title}
                  </Link>{" "}
                  <span className="muted">(revision {c.source_head_no})</span>
                </th>
                <td>
                  <Link to={`/projects/${ed.target_project_id}/chapters/${c.target_chapter_id}`}>
                    {c.target_title}
                  </Link>
                  {c.suggested_title && c.suggested_title !== c.target_title ? (
                    <div className="muted">Suggested title: {c.suggested_title}</div>
                  ) : null}
                </td>
                <td>
                  {STATUS[c.status] ?? c.status}
                  {c.stale ? (
                    <div className="tag tag-gilt">Original changed since revision {c.source_revision_no}</div>
                  ) : null}
                </td>
                <td>
                  <button
                    type="button"
                    className="btn btn-small"
                    disabled={!approved || actions.translate.isPending || (!!prov && !model)}
                    title={approved ? undefined : "Mark the original chapter Approved first."}
                    onClick={() =>
                      actions.translate.mutate(
                        {
                          id: ed.id,
                          body: {
                            source_chapter_id: c.source_chapter_id,
                            source_revision_no: c.source_head_no,
                            provider_id: prov || null,
                            model_name: model || null,
                            client_request_id: crypto.randomUUID().replace(/-/g, ""),
                          },
                        },
                        { onSuccess: () => announce(`Translating “${c.source_title}”`) },
                      )
                    }
                  >
                    {c.status === "not_started" ? "Translate" : "Translate again"}
                  </button>
                  {!approved ? <div className="muted">Original not approved yet</div> : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {ed.chapters.some((c) => c.issues.length) ? (
        <>
          <h3>To check before you accept</h3>
          <p className="hint">
            Idioms, terminology, names and structure the translation may have changed. Open the edition's
            chapter to accept or reject the translation; mark each item when you have looked at it.
          </p>
          {ed.chapters
            .filter((c) => c.issues.length)
            .map((c) => (
              <div key={c.target_chapter_id}>
                <h4>{c.source_title}</h4>
                <ul className="translation-issues">
                  {c.issues.map((it, i) => (
                    <li key={i} data-state={it.state}>
                      <span className="tag">{it.kind}</span> {it.message}
                      {it.source ? <span className="muted"> (“{it.source}”)</span> : null}{" "}
                      <label className="inline-check">
                        <input
                          type="checkbox"
                          checked={it.state === "reviewed"}
                          onChange={(e) =>
                            actions.reviewIssue.mutate({
                              id: ed.id,
                              chapterId: c.target_chapter_id,
                              index: i,
                              state: e.target.checked ? "reviewed" : "open",
                            })
                          }
                        />
                        Checked
                      </label>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
        </>
      ) : null}
      <h3>Required term translations</h3>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const map: Record<string, string> = {};
          for (const line of terms.split("\n")) {
            const [k, ...v] = line.split("=");
            if (k?.trim() && v.join("=").trim()) map[k.trim()] = v.join("=").trim();
          }
          actions.terms.mutate(
            { id: ed.id, term_map: map },
            { onSuccess: () => announce("Term list saved") },
          );
        }}
      >
        <div className="field">
          <label htmlFor={`${id}-terms`}>One per line: original term = translation</label>
          <textarea id={`${id}-terms`} rows={4} value={terms} onChange={(e) => setTerms(e.target.value)} />
        </div>
        <button type="submit" className="btn btn-small">
          Save term list
        </button>
      </form>
    </section>
  );
}

/** In the chapter editor: which chapter this one translates, and its translations in other languages. */
export function ChapterTranslations({ projectId, chapterId }: { projectId: string; chapterId: string }) {
  const id = useId();
  const links = useChapterLinks(projectId, chapterId);
  if (!links.data) return null;
  const { translation_of: of, translations } = links.data;
  if (!of && !translations.length) return null;
  return (
    <section className="notes chapter-languages" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>Other languages</h2>
      <ul>
        {of ? (
          <li>
            Translated from <Link to={of.link}>“{of.chapter_title}”</Link> in {of.project_title} (
            {of.language}), revision {of.source_revision_no}.
          </li>
        ) : null}
        {translations.map((t) => (
          <li key={t.chapter_id}>
            <span className="tag">{t.language}</span> <Link to={t.link}>“{t.chapter_title}”</Link>{" "}
            {STATUS[t.status] ?? t.status}
            {t.stale ? " (this chapter has changed since it was translated)" : ""}
          </li>
        ))}
      </ul>
    </section>
  );
}
