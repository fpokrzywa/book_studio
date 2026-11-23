import { useId, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import {
  useCanon,
  useCreateSeries,
  useIssues,
  useSeries,
  useSeriesActions,
  useSeriesList,
  type CanonKind,
  type Entity,
  type Fact,
  type Issue,
  type Relationship,
  type ResolveAction,
  type Series,
} from "../../api/advanced";
import { useProjects } from "../../api/hooks";
import { useAnnounce } from "../../components/Announcer";
import { PageHeader, usePageTitle } from "../../components/Misc";
import { EmptyState, ErrorState, InlineError, Loading } from "../../components/States";
import { relativeTime } from "../../lib/format";
import { RelationshipMap } from "./RelationshipMap";

const KINDS: [CanonKind, string][] = [
  ["character", "Characters"],
  ["location", "Places"],
  ["thread", "Plot threads"],
  ["event", "Events (chronology)"],
  ["term", "Terms"],
  ["other", "Other"],
];
const STATUS_LABEL = {
  canon: "Canon",
  suggested: "Suggestion, not canon yet",
  rejected: "Rejected",
} as const;
const ORIGIN_LABEL: Record<string, string> = {
  author: "added by you",
  ai_suggested: "suggested by AI",
  book_note: "from a book's continuity notes",
};

/** The Series menu: every series, and a form to start one. */
export function SeriesHome() {
  usePageTitle("Series");
  const id = useId();
  const list = useSeriesList();
  const create = useCreateSeries();
  const announce = useAnnounce();
  const [title, setTitle] = useState("");
  return (
    <>
      <PageHeader
        title="Series"
        intro="Books that share a world. Keep one story bible for all of them, then check new chapters against it. Only what you approve counts as canon."
      />
      <div className="stack">
        <section className="panel" aria-labelledby={`${id}-new`}>
          <h2 id={`${id}-new`}>New series</h2>
          <form
            className="form-row adv-row"
            onSubmit={(e) => {
              e.preventDefault();
              if (!title.trim()) return;
              create.mutate(
                { title: title.trim(), description: "" },
                { onSuccess: (s) => (announce(`Series “${s.title}” created`), setTitle("")) },
              );
            }}
          >
            <div className="field">
              <label htmlFor={`${id}-t`}>Series title</label>
              <input
                id={`${id}-t`}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={200}
              />
            </div>
            <button type="submit" className="btn btn-primary" disabled={create.isPending || !title.trim()}>
              Create series
            </button>
          </form>
          {create.error ? <InlineError error={create.error} /> : null}
        </section>
        {list.isError ? <ErrorState error={list.error} onRetry={() => void list.refetch()} /> : null}
        {list.isPending ? (
          <Loading label="Loading series" />
        ) : list.data?.length ? (
          <ul className="link-list series-list">
            {list.data.map((s) => (
              <li key={s.id}>
                <Link to={`/series/${s.id}`}>{s.title}</Link>{" "}
                <span className="muted">
                  {s.books.length} book{s.books.length === 1 ? "" : "s"}
                  {s.counts.open_issues ? `, ${s.counts.open_issues} open continuity question(s)` : ""}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No series yet">
            Create one above, then add the books that belong to it.
          </EmptyState>
        )}
      </div>
    </>
  );
}

const TABS = [
  ["books", "Books"],
  ["bible", "Story bible"],
  ["relationships", "Relationships"],
  ["continuity", "Continuity review"],
] as const;
type Tab = (typeof TABS)[number][0];

export function SeriesPage() {
  const { seriesId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find(([t]) => t === params.get("tab"))?.[0] ?? "books") as Tab;
  const series = useSeries(seriesId);
  usePageTitle(series.data?.title ?? "Series");
  if (series.isError) return <ErrorState error={series.error} onRetry={() => void series.refetch()} />;
  if (!series.data) return <Loading label="Loading the series" />;
  const s = series.data;
  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to="/series">Series</Link>
      </nav>
      <PageHeader
        title={s.title}
        intro="One story bible for every book in the series. AI suggestions stay separate until you approve them."
      />
      <nav className="plan-tabs" aria-label="Series sections">
        <ol>
          {TABS.map(([t, label]) => (
            <li key={t}>
              <Link
                to={`?tab=${t}`}
                aria-current={t === tab ? "page" : undefined}
                onClick={() => setParams({ tab: t })}
              >
                {label}
                {t === "continuity" && s.counts.open_issues ? ` (${s.counts.open_issues})` : ""}
                {t === "bible" && s.counts.suggested ? ` (${s.counts.suggested} to review)` : ""}
              </Link>
            </li>
          ))}
        </ol>
      </nav>
      {tab === "books" ? <BooksTab series={s} /> : null}
      {tab === "bible" ? <BibleTab series={s} /> : null}
      {tab === "relationships" ? <RelationshipsTab series={s} /> : null}
      {tab === "continuity" ? <ContinuityTab series={s} /> : null}
    </>
  );
}

// ---------- books ----------

function BooksTab({ series: s }: { series: Series }) {
  const id = useId();
  const projects = useProjects({ status: "active" });
  const actions = useSeriesActions(s.id);
  const announce = useAnnounce();
  const [pick, setPick] = useState("");
  const inSeries = new Set(s.books.map((b) => b.project_id));
  const candidates = (projects.data?.items ?? []).filter((p) => !inSeries.has(p.id));
  const error = actions.addBook.error ?? actions.removeBook.error ?? actions.importNotes.error;
  return (
    <div className="stack">
      <section className="panel" aria-labelledby={`${id}-books`}>
        <h2 id={`${id}-books`}>Books in reading order</h2>
        {error ? <InlineError error={error} /> : null}
        {s.books.length ? (
          <ol className="series-books">
            {s.books.map((b) => (
              <li key={b.project_id}>
                <Link to={`/projects/${b.project_id}`}>{b.title}</Link>{" "}
                <span className="muted">({b.language})</span>
                <div className="row-actions">
                  <button
                    type="button"
                    className="btn btn-small"
                    disabled={actions.importNotes.isPending}
                    onClick={() =>
                      actions.importNotes.mutate(b.project_id, {
                        onSuccess: (r) =>
                          announce(
                            `${r.facts_added} note(s) imported; ${r.skipped_existing} already in the story bible`,
                          ),
                      })
                    }
                  >
                    Import its story notes
                  </button>
                  <button
                    type="button"
                    className="btn btn-small"
                    onClick={() => actions.removeBook.mutate(b.project_id)}
                  >
                    Remove from series
                  </button>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <p className="muted">No books yet.</p>
        )}
        <p className="hint">
          Importing a book's story notes adds its confirmed notes as canon and the rest as suggestions you can
          approve or reject. The book itself is not changed.
        </p>
        <form
          className="form-row adv-row"
          onSubmit={(e) => {
            e.preventDefault();
            if (pick)
              actions.addBook.mutate(pick, { onSuccess: () => (announce("Book added"), setPick("")) });
          }}
        >
          <div className="field">
            <label htmlFor={`${id}-pick`}>Add a book</label>
            <select id={`${id}-pick`} value={pick} onChange={(e) => setPick(e.target.value)}>
              <option value="">Choose a book…</option>
              {candidates.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title}
                </option>
              ))}
            </select>
          </div>
          <button type="submit" className="btn" disabled={!pick || actions.addBook.isPending}>
            Add to series
          </button>
        </form>
      </section>
    </div>
  );
}

// ---------- story bible ----------

function StatusTag({ status, origin }: { status: keyof typeof STATUS_LABEL; origin: string }) {
  return (
    <span className={`tag canon-${status}`} title={ORIGIN_LABEL[origin] ?? origin}>
      {STATUS_LABEL[status]}
    </span>
  );
}

function BibleTab({ series: s }: { series: Series }) {
  const id = useId();
  const canon = useCanon(s.id);
  const actions = useSeriesActions(s.id);
  const announce = useAnnounce();
  const [kind, setKind] = useState<CanonKind>("character");
  const [name, setName] = useState("");
  const [aliases, setAliases] = useState("");
  const [summary, setSummary] = useState("");
  if (canon.isError) return <ErrorState error={canon.error} onRetry={() => void canon.refetch()} />;
  if (!canon.data) return <Loading label="Loading the story bible" />;
  const c = canon.data;
  return (
    <div className="stack">
      <section className="panel" aria-labelledby={`${id}-add`}>
        <h2 id={`${id}-add`}>Add to the story bible</h2>
        <form
          className="form-row adv-row"
          onSubmit={(e) => {
            e.preventDefault();
            actions.addEntity.mutate(
              {
                kind,
                name: name.trim(),
                aliases: aliases
                  .split(",")
                  .map((a) => a.trim())
                  .filter(Boolean),
                summary,
              },
              {
                onSuccess: (en) => (
                  announce(`${en.name} added as canon`),
                  setName(""),
                  setAliases(""),
                  setSummary("")
                ),
              },
            );
          }}
        >
          <div className="field">
            <label htmlFor={`${id}-k`}>Kind</label>
            <select id={`${id}-k`} value={kind} onChange={(e) => setKind(e.target.value as CanonKind)}>
              {KINDS.map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor={`${id}-n`}>Name</label>
            <input id={`${id}-n`} value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
          </div>
          <div className="field">
            <label htmlFor={`${id}-a`}>Other names (comma separated)</label>
            <input id={`${id}-a`} value={aliases} onChange={(e) => setAliases(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor={`${id}-s`}>Summary</label>
            <input
              id={`${id}-s`}
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              maxLength={2000}
            />
          </div>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={!name.trim() || actions.addEntity.isPending}
          >
            Add
          </button>
        </form>
        {actions.addEntity.error ? <InlineError error={actions.addEntity.error} /> : null}
      </section>

      {c.chronology_warnings.length ? (
        <section className="panel notes" aria-labelledby={`${id}-chrono`}>
          <h2 id={`${id}-chrono`}>Chronology to check</h2>
          <ul>
            {c.chronology_warnings.map((w, i) => (
              <li key={i}>{w.message}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {KINDS.map(([k, label]) => {
        const rows = c.entities.filter((e) => e.kind === k);
        if (!rows.length) return null;
        return (
          <section key={k} className="panel" aria-labelledby={`${id}-${k}`}>
            <h2 id={`${id}-${k}`}>{label}</h2>
            <ul className="canon-list">
              {rows.map((e) => (
                <EntityCard key={e.id} seriesId={s.id} entity={e} books={s.books} />
              ))}
            </ul>
          </section>
        );
      })}
      {!c.entities.length ? (
        <EmptyState title="The story bible is empty">
          Add characters, places and plot threads above, or import a book's story notes from the Books tab.
        </EmptyState>
      ) : null}
    </div>
  );
}

function EntityCard({
  seriesId,
  entity: e,
  books,
}: {
  seriesId: string;
  entity: Entity;
  books: Series["books"];
}) {
  const id = useId();
  const actions = useSeriesActions(seriesId);
  const announce = useAnnounce();
  const [attr, setAttr] = useState("");
  const [value, setValue] = useState("");
  const [when, setWhen] = useState("");
  const [book, setBook] = useState("");
  const current = e.facts.filter((f) => !f.superseded_by);
  const earlier = e.facts.filter((f) => f.superseded_by);
  const error = actions.addFact.error ?? actions.patchFact.error ?? actions.patchEntity.error;
  return (
    <li className="canon-card" data-status={e.status}>
      <h3>
        {e.name} <StatusTag status={e.status} origin={e.origin} />
      </h3>
      {e.aliases.length ? <p className="muted">Also called: {e.aliases.join(", ")}</p> : null}
      {e.summary ? <p>{e.summary}</p> : null}
      {e.status !== "canon" ? (
        <div className="row-actions">
          <button
            type="button"
            className="btn btn-small"
            onClick={() => actions.patchEntity.mutate({ id: e.id, body: { status: "canon" } })}
          >
            Approve as canon
          </button>
          {e.status === "suggested" ? (
            <button
              type="button"
              className="btn btn-small"
              onClick={() => actions.patchEntity.mutate({ id: e.id, body: { status: "rejected" } })}
            >
              Reject
            </button>
          ) : null}
        </div>
      ) : null}
      {error ? <InlineError error={error} /> : null}
      {current.length ? (
        <table className="data-table">
          <caption className="visually-hidden">Facts about {e.name}</caption>
          <thead>
            <tr>
              <th scope="col">Fact</th>
              <th scope="col">Value</th>
              <th scope="col">Story time</th>
              <th scope="col">Book</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {current.map((f) => (
              <FactRow key={f.id} seriesId={seriesId} fact={f} />
            ))}
          </tbody>
        </table>
      ) : null}
      {earlier.length ? (
        <details>
          <summary>Earlier values ({earlier.length})</summary>
          <ul>
            {earlier.map((f) => (
              <li key={f.id}>
                {f.attribute}: <s>{f.value}</s>{" "}
                <span className="muted">replaced {relativeTime(f.updated_at)}</span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <form
        className="form-row compact"
        onSubmit={(ev) => {
          ev.preventDefault();
          actions.addFact.mutate(
            {
              entity_id: e.id,
              attribute: attr.trim(),
              value: value.trim(),
              story_time: when.trim() || null,
              book_project_id: book || null,
            },
            { onSuccess: () => (announce("Fact added as canon"), setAttr(""), setValue(""), setWhen("")) },
          );
        }}
      >
        <div className="field">
          <label htmlFor={`${id}-fa`}>Fact</label>
          <input
            id={`${id}-fa`}
            value={attr}
            placeholder="eye colour"
            onChange={(ev) => setAttr(ev.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor={`${id}-fv`}>Value</label>
          <input id={`${id}-fv`} value={value} onChange={(ev) => setValue(ev.target.value)} />
        </div>
        <div className="field">
          <label htmlFor={`${id}-fw`}>Story time (optional)</label>
          <input
            id={`${id}-fw`}
            value={when}
            placeholder="year 1203"
            onChange={(ev) => setWhen(ev.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor={`${id}-fb`}>Established in</label>
          <select id={`${id}-fb`} value={book} onChange={(ev) => setBook(ev.target.value)}>
            <option value="">Not tied to a book</option>
            {books.map((b) => (
              <option key={b.project_id} value={b.project_id}>
                {b.title}
              </option>
            ))}
          </select>
        </div>
        <button type="submit" className="btn btn-small" disabled={!attr.trim() || !value.trim()}>
          Add fact
        </button>
      </form>
    </li>
  );
}

function FactRow({ seriesId, fact: f }: { seriesId: string; fact: Fact }) {
  const actions = useSeriesActions(seriesId);
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(f.value);
  const id = useId();
  const prov = f.provenance as { chapter_id?: string; excerpt?: string; from_issue?: string };
  return (
    <tr data-status={f.status}>
      <th scope="row">{f.attribute}</th>
      <td>
        {editing ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              actions.patchFact.mutate({ id: f.id, body: { value } }, { onSuccess: () => setEditing(false) });
            }}
          >
            <label htmlFor={`${id}-v`} className="visually-hidden">
              New value for {f.attribute}
            </label>
            <input id={`${id}-v`} value={value} onChange={(e) => setValue(e.target.value)} />
            <button type="submit" className="btn btn-small">
              Save
            </button>
            <button type="button" className="btn btn-small" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </form>
        ) : (
          <>
            <span className="fact-value">{f.value}</span>{" "}
            <button type="button" className="btn btn-link" onClick={() => setEditing(true)}>
              Edit
            </button>
          </>
        )}
        {prov.excerpt ? <div className="muted provenance">From the text: “{prov.excerpt}”</div> : null}
      </td>
      <td>{f.story_time ?? "—"}</td>
      <td>{f.book_title ?? "—"}</td>
      <td>
        <StatusTag status={f.status} origin={f.origin} />{" "}
        {f.status === "suggested" ? (
          <>
            <button
              type="button"
              className="btn btn-small"
              onClick={() => actions.patchFact.mutate({ id: f.id, body: { status: "canon" } })}
            >
              Approve
            </button>
            <button
              type="button"
              className="btn btn-small"
              onClick={() => actions.patchFact.mutate({ id: f.id, body: { status: "rejected" } })}
            >
              Reject
            </button>
          </>
        ) : null}
      </td>
    </tr>
  );
}

// ---------- relationships ----------

function RelationshipsTab({ series: s }: { series: Series }) {
  const id = useId();
  const canon = useCanon(s.id);
  const actions = useSeriesActions(s.id);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [label, setLabel] = useState("");
  const people = useMemo(
    () => (canon.data?.entities ?? []).filter((e) => e.kind === "character" && e.status !== "rejected"),
    [canon.data],
  );
  if (canon.isError) return <ErrorState error={canon.error} onRetry={() => void canon.refetch()} />;
  if (!canon.data) return <Loading label="Loading relationships" />;
  const name = (eid: string) => canon.data.entities.find((e) => e.id === eid)?.name ?? "?";
  const rels = canon.data.relationships.filter((r) => r.status !== "rejected");
  return (
    <div className="stack">
      <section className="panel" aria-labelledby={`${id}-list`}>
        <h2 id={`${id}-list`}>Who is who to whom</h2>
        <p className="hint">
          Read each line as “first name is the second name's …”. The continuity review checks family words.
        </p>
        {rels.length ? (
          <ul className="rel-list">
            {rels.map((r: Relationship) => (
              <li key={r.id}>
                <strong>{name(r.from_entity_id)}</strong> is <strong>{name(r.to_entity_id)}</strong>'s{" "}
                {r.label} <StatusTag status={r.status} origin={r.origin} />
                {r.status === "suggested" ? (
                  <button
                    type="button"
                    className="btn btn-small"
                    onClick={() => actions.patchRelationship.mutate({ id: r.id, body: { status: "canon" } })}
                  >
                    Approve
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No relationships yet.</p>
        )}
        <form
          className="form-row adv-row"
          onSubmit={(e) => {
            e.preventDefault();
            actions.addRelationship.mutate(
              { from_entity_id: from, to_entity_id: to, label: label.trim() },
              { onSuccess: () => setLabel("") },
            );
          }}
        >
          <div className="field">
            <label htmlFor={`${id}-f`}>Character</label>
            <select id={`${id}-f`} value={from} onChange={(e) => setFrom(e.target.value)}>
              <option value="">Choose…</option>
              {people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor={`${id}-l`}>is … of</label>
            <input
              id={`${id}-l`}
              value={label}
              placeholder="brother"
              onChange={(e) => setLabel(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor={`${id}-t`}>Character</label>
            <select id={`${id}-t`} value={to} onChange={(e) => setTo(e.target.value)}>
              <option value="">Choose…</option>
              {people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <button type="submit" className="btn" disabled={!from || !to || from === to || !label.trim()}>
            Add relationship
          </button>
        </form>
        {actions.addRelationship.error ? <InlineError error={actions.addRelationship.error} /> : null}
      </section>
      <section className="panel" aria-labelledby={`${id}-map`}>
        <h2 id={`${id}-map`}>Map</h2>
        <p className="hint">
          A picture of the list above. Solid lines are canon; dashed lines are suggestions.
        </p>
        <RelationshipMap people={people} relationships={rels} />
      </section>
    </div>
  );
}

// ---------- continuity ----------

const STATE_LABEL: Record<Issue["state"], string> = {
  open: "Open",
  keep_canon: "Kept canon (the text needs changing)",
  canon_updated: "Canon updated to match the text",
  intended: "Intended (left as written)",
};

function ContinuityTab({ series: s }: { series: Series }) {
  const id = useId();
  const issues = useIssues(s.id);
  const actions = useSeriesActions(s.id);
  const announce = useAnnounce();
  const [scope, setScope] = useState("");
  const [showResolved, setShowResolved] = useState(false);
  const all = issues.data ?? [];
  const visible = all.filter((i) => i.present && (showResolved || i.state === "open"));
  const gone = all.filter((i) => !i.present);
  return (
    <div className="stack">
      <section className="panel" aria-labelledby={`${id}-run`}>
        <h2 id={`${id}-run`}>Check chapters against canon</h2>
        <p className="hint">
          Compares the current text of each chapter with approved canon: eye and hair colour, ages, characters
          canon says are dead, and family relationships. Findings point at passages; they never change your
          text. Your decisions are kept when you run the check again.
        </p>
        <form
          className="form-row adv-row"
          onSubmit={(e) => {
            e.preventDefault();
            actions.review.mutate(scope || null, {
              onSuccess: (r) =>
                announce(`Checked ${r.checked_chapters} chapter(s); ${r.new} new question(s)`),
            });
          }}
        >
          <div className="field">
            <label htmlFor={`${id}-scope`}>Books to check</label>
            <select id={`${id}-scope`} value={scope} onChange={(e) => setScope(e.target.value)}>
              <option value="">Every book in the series</option>
              {s.books.map((b) => (
                <option key={b.project_id} value={b.project_id}>
                  {b.title}
                </option>
              ))}
            </select>
          </div>
          <button type="submit" className="btn btn-primary" disabled={actions.review.isPending}>
            {actions.review.isPending ? "Checking…" : "Run the check"}
          </button>
        </form>
        {actions.review.error ? <InlineError error={actions.review.error} /> : null}
        <label className="inline-check">
          <input type="checkbox" checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)} />
          Show questions you already resolved
        </label>
      </section>
      {issues.isError ? <ErrorState error={issues.error} onRetry={() => void issues.refetch()} /> : null}
      {visible.length ? (
        <ul className="issue-list" aria-label="Continuity questions">
          {visible.map((i) => (
            <IssueCard key={i.id} seriesId={s.id} issue={i} />
          ))}
        </ul>
      ) : issues.data ? (
        <EmptyState title="Nothing to resolve">
          No open contradictions with canon were found in the last check.
        </EmptyState>
      ) : (
        <Loading label="Loading continuity questions" />
      )}
      {gone.length ? (
        <details className="panel">
          <summary>No longer found in the text ({gone.length})</summary>
          <ul>
            {gone.map((i) => (
              <li key={i.id}>
                {i.book_title}, “{i.chapter_title}”: {i.message}{" "}
                <span className="muted">({STATE_LABEL[i.state]})</span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

function IssueCard({ seriesId, issue: i }: { seriesId: string; issue: Issue }) {
  const id = useId();
  const actions = useSeriesActions(seriesId);
  const announce = useAnnounce();
  const [note, setNote] = useState(i.resolution_note ?? "");
  const act = (action: ResolveAction) =>
    actions.resolve.mutate({ id: i.id, action, note }, { onSuccess: (r) => announce(STATE_LABEL[r.state]) });
  return (
    <li className="issue-card" data-state={i.state}>
      <p className="issue-where">
        {i.book_title}, <Link to={i.link}>“{i.chapter_title}”, open the passage</Link>{" "}
        <span className="muted">(revision {i.revision_no})</span>
      </p>
      <p>{i.message}</p>
      <blockquote className="excerpt">{i.excerpt}</blockquote>
      <p>
        <span className="tag">{STATE_LABEL[i.state]}</span>
        {i.resolution_note ? <span className="muted"> {i.resolution_note}</span> : null}
      </p>
      <div className="field">
        <label htmlFor={`${id}-note`}>Note for your decision (optional)</label>
        <input id={`${id}-note`} value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
      </div>
      <div className="row-actions" role="group" aria-label="Resolve this question">
        {i.state === "open" ? (
          <>
            <button type="button" className="btn btn-small" onClick={() => act("keep_canon")}>
              Canon is right, I'll fix the text
            </button>
            <button
              type="button"
              className="btn btn-small"
              disabled={!i.found_value}
              onClick={() => act("update_canon")}
            >
              The text is right, update canon
            </button>
            <button type="button" className="btn btn-small" onClick={() => act("intended")}>
              Intended, leave it
            </button>
          </>
        ) : (
          <button type="button" className="btn btn-small" onClick={() => act("reopen")}>
            Reopen
          </button>
        )}
      </div>
      {actions.resolve.error ? <InlineError error={actions.resolve.error} /> : null}
    </li>
  );
}
