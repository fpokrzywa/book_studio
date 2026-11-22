import { useEffect, useId, useState } from "react";
import { Link, useSearchParams } from "react-router";
import type { ProjectType, PublicationFormat } from "../../api/client";
import { useActivity, useProjects, type LibraryQuery } from "../../api/hooks";
import { PageHeader } from "../../components/Misc";
import { EmptyState, ErrorState, Loading } from "../../components/States";
import { FORMATS, n, PROJECT_TYPES } from "../../lib/format";
import { ActivityList } from "../activity/ActivityList";
import { ProjectVolume } from "./ProjectVolume";

const SORTS: { value: NonNullable<LibraryQuery["sort"]>; label: string }[] = [
  { value: "updated_at", label: "Last edited" },
  { value: "title", label: "Title" },
  { value: "project_type", label: "Kind of book" },
  { value: "language", label: "Language" },
  { value: "audience", label: "Audience" },
  { value: "target_word_count", label: "Target length" },
  { value: "created_at", label: "Date created" },
];

function readQuery(params: URLSearchParams): LibraryQuery {
  const q: LibraryQuery = {
    status: (params.get("status") as LibraryQuery["status"]) ?? "active",
    sort: (params.get("sort") as LibraryQuery["sort"]) ?? "updated_at",
  };
  const order = params.get("order");
  q.order = order === "asc" || order === "desc" ? order : q.sort === "title" ? "asc" : "desc";
  const text = params.get("q");
  if (text) q.q = text;
  const type = params.get("type");
  if (type) q.project_type = type as ProjectType;
  const format = params.get("format");
  if (format) q.publication_format = format as PublicationFormat;
  return q;
}

export function LibraryPage() {
  const [params, setParams] = useSearchParams();
  const query = readQuery(params);
  const projects = useProjects(query);
  const activity = useActivity(undefined, 8);
  const [text, setText] = useState(query.q ?? "");
  const id = useId();

  const update = (key: string, value: string | null) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value === null || value === "") next.delete(key);
        else next.set(key, value);
        return next;
      },
      { replace: true },
    );
  };

  useEffect(() => {
    const current = params.get("q") ?? "";
    if (text === current) return;
    const t = setTimeout(() => update("q", text.trim() || null), 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  const filtered = Boolean(query.q || query.project_type || query.publication_format);
  const items = projects.data?.items ?? [];

  return (
    <>
      <PageHeader
        title="Library"
        intro="Every book you are working on. Open one to write, or start something new."
        actions={
          <Link to="/new" className="btn btn-primary">
            New book
          </Link>
        }
      />
      <div className="library-layout">
        <section aria-labelledby={`${id}-shelf`}>
          <h2 id={`${id}-shelf`} className="visually-hidden">
            Books
          </h2>
          <div role="search" className="controls" aria-label="Find books">
            <div className="field">
              <label htmlFor={`${id}-q`}>Search books</label>
              <input id={`${id}-q`} type="search" value={text} onChange={(e) => setText(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor={`${id}-type`}>Kind of book</label>
              <select
                id={`${id}-type`}
                value={query.project_type ?? ""}
                onChange={(e) => update("type", e.target.value)}
              >
                <option value="">All kinds</option>
                {PROJECT_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor={`${id}-format`}>Format</label>
              <select
                id={`${id}-format`}
                value={query.publication_format ?? ""}
                onChange={(e) => update("format", e.target.value)}
              >
                <option value="">Any format</option>
                {FORMATS.map((f) => (
                  <option key={f.value} value={f.value}>
                    {f.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor={`${id}-sort`}>Sort by</label>
              <select id={`${id}-sort`} value={query.sort} onChange={(e) => update("sort", e.target.value)}>
                {SORTS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="button"
              className="btn"
              onClick={() => update("order", query.order === "asc" ? "desc" : "asc")}
              aria-label={`Sort direction: ${query.order === "asc" ? "ascending" : "descending"}. Change direction`}
            >
              {query.order === "asc" ? "Ascending" : "Descending"}
            </button>
          </div>

          <fieldset className="segmented">
            <legend className="visually-hidden">Show</legend>
            {(
              [
                ["active", "Active"],
                ["archived", "Archived"],
                ["all", "All"],
              ] as const
            ).map(([value, label]) => (
              <label key={value}>
                <input
                  type="radio"
                  name={`${id}-status`}
                  value={value}
                  checked={query.status === value}
                  onChange={() => update("status", value === "active" ? null : value)}
                />
                {label}
              </label>
            ))}
          </fieldset>

          {projects.isPending ? (
            <Loading label="Loading your library" />
          ) : projects.isError ? (
            <ErrorState error={projects.error} onRetry={() => void projects.refetch()} />
          ) : items.length === 0 ? (
            filtered || query.status !== "active" ? (
              <EmptyState
                title="No books match"
                action={
                  <button
                    type="button"
                    className="btn"
                    onClick={() => {
                      setText("");
                      setParams({}, { replace: true });
                    }}
                  >
                    Clear filters
                  </button>
                }
              >
                Nothing in this view matches the current search and filters.
              </EmptyState>
            ) : (
              <EmptyState
                title="No books yet"
                action={
                  <Link to="/new" className="btn btn-primary">
                    Start your first book
                  </Link>
                }
              >
                Start with a working title. Chapters, notes and exports all live in the project, saved on this
                computer.
              </EmptyState>
            )
          ) : (
            <>
              <p className="muted" role="status" style={{ marginBottom: "var(--space-3)" }}>
                {projects.data.total === 1 ? "1 book" : `${n(projects.data.total)} books`}
              </p>
              <ul className="shelf">
                {items.map((p) => (
                  <li key={p.id}>
                    <ProjectVolume project={p} />
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>

        <aside className="panel" aria-labelledby={`${id}-recent`}>
          <h2 id={`${id}-recent`}>Recent activity</h2>
          {activity.isPending ? (
            <Loading />
          ) : activity.isError ? (
            <p className="muted">Activity could not be loaded.</p>
          ) : activity.data.length === 0 ? (
            <p className="muted">Changes you make will be listed here.</p>
          ) : (
            <>
              <ActivityList items={activity.data} />
              <p style={{ marginTop: "var(--space-4)" }}>
                <Link to="/activity">All activity</Link>
              </p>
            </>
          )}
        </aside>
      </div>
    </>
  );
}
