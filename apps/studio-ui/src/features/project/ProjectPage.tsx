import { useId, useState, type CSSProperties } from "react";
import { Link, useNavigate, useParams } from "react-router";
import type { Project } from "../../api/client";
import { ApiError } from "../../api/client";
import {
  useActivity,
  useDuplicateProject,
  useExports,
  useProject,
  useSetArchived,
  useUpdateProject,
} from "../../api/hooks";
import { useBackups, useCreateBackup, useExportAs } from "../../api/manuscript";
import { useAnnounce } from "../../components/Announcer";
import { ConfirmDialog, Dialog } from "../../components/Dialog";
import { usePageTitle } from "../../components/Misc";
import { EmptyState, ErrorState, InlineError, Loading } from "../../components/States";
import {
  absoluteTime,
  formatList,
  languageName,
  n,
  relativeTime,
  spineVar,
  typeLabel,
  words,
} from "../../lib/format";
import { ActivityList } from "../activity/ActivityList";
import { ManuscriptTree } from "./ManuscriptTree";
import { initialValues, ProjectForm } from "./ProjectForm";

export function ProjectPage() {
  const { projectId = "" } = useParams();
  const project = useProject(projectId);

  if (project.isPending) return <Loading label="Opening the book" />;
  if (project.isError) {
    if (project.error instanceof ApiError && project.error.status === 404) {
      return (
        <EmptyState title="Book not found" action={<Link to="/">Back to the library</Link>}>
          There is no book at this address. It may have been typed incorrectly.
        </EmptyState>
      );
    }
    return <ErrorState error={project.error} onRetry={() => void project.refetch()} />;
  }
  return <ProjectView project={project.data} />;
}

function ProjectView({ project }: { project: Project }) {
  usePageTitle(project.title);
  const announce = useAnnounce();
  const navigate = useNavigate();
  const [editing, setEditing] = useState(false);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const update = useUpdateProject(project.id);
  const setArchived = useSetArchived(project.id);
  const duplicate = useDuplicateProject(project.id);
  const archived = project.status === "archived";

  return (
    <>
      {archived ? (
        <div className="banner" role="note">
          <span>
            <strong>This book is archived.</strong> It is read-only until you unarchive it. Nothing has been
            deleted.
          </span>
          <button
            type="button"
            className="btn btn-small"
            disabled={setArchived.isPending}
            onClick={() =>
              setArchived.mutate(false, { onSuccess: (p) => announce(`Unarchived “${p.title}”`) })
            }
          >
            Unarchive
          </button>
        </div>
      ) : null}

      <header className="project-head" style={{ "--spine": spineVar(project.project_type) } as CSSProperties}>
        <div className="spine" aria-hidden="true" />
        <div>
          <h1>{project.title}</h1>
          {project.subtitle ? <p className="subtitle">{project.subtitle}</p> : null}
          {project.description ? <p className="description">{project.description}</p> : null}
          <dl className="facts">
            <div>
              <dt>Author</dt>
              <dd>{project.author_name ?? "Not set"}</dd>
            </div>
            <div>
              <dt>Kind</dt>
              <dd>{typeLabel(project.project_type)}</dd>
            </div>
            <div>
              <dt>Language</dt>
              <dd>{languageName(project.language)}</dd>
            </div>
            <div>
              <dt>Audience</dt>
              <dd>{project.audience ?? "Not set"}</dd>
            </div>
            <div>
              <dt>Written</dt>
              <dd>
                {project.target_word_count != null
                  ? `${n(project.word_count)} of ${n(project.target_word_count)} words`
                  : words(project.word_count)}
              </dd>
            </div>
            <div>
              <dt>Formats</dt>
              <dd>{formatList(project.publication_formats)}</dd>
            </div>
          </dl>
          <div className="page-actions" style={{ marginTop: "var(--space-5)" }}>
            <button type="button" className="btn" disabled={archived} onClick={() => setEditing(true)}>
              Edit details
            </button>
            {!archived ? (
              <Link className="btn" to={`/import?into=${project.id}`}>
                Import chapters
              </Link>
            ) : null}
            <button
              type="button"
              className="btn"
              disabled={duplicate.isPending}
              onClick={() =>
                duplicate.mutate(undefined, {
                  onSuccess: (copy) => {
                    announce(`Duplicated as “${copy.title}”`);
                    navigate(`/projects/${copy.id}`);
                  },
                })
              }
            >
              Duplicate
            </button>
            {!archived ? (
              <button type="button" className="btn" onClick={() => setConfirmArchive(true)}>
                Archive
              </button>
            ) : null}
          </div>
          {duplicate.isError ? <InlineError error={duplicate.error} /> : null}
          {setArchived.isError ? <InlineError error={setArchived.error} /> : null}
        </div>
      </header>

      <div className="two-col">
        <ManuscriptTree project={project} />
        <div className="stack">
          <section className="panel" aria-labelledby="project-research">
            <h2 id="project-research">Research and evidence</h2>
            <ul className="link-list">
              <li>
                <Link to={`/projects/${project.id}/knowledge`}>Sources</Link>{" "}
                <span className="muted">reference files AI can quote and cite</span>
              </li>
              <li>
                <Link to={`/projects/${project.id}/evidence`}>Evidence ledger</Link>{" "}
                <span className="muted">claims and the exact passages behind them</span>
              </li>
              <li>
                <Link to={`/projects/${project.id}/interview`}>Interview</Link>{" "}
                <span className="muted">your own stories, in your own words</span>
              </li>
            </ul>
          </section>
          <ExportsSection project={project} />
          <BackupSection project={project} />
          <section className="panel" aria-labelledby="project-activity">
            <h2 id="project-activity">History of this book</h2>
            <ProjectActivity projectId={project.id} />
          </section>
        </div>
      </div>

      <Dialog isOpen={editing} onClose={() => setEditing(false)} title="Edit book details">
        <ProjectForm
          initial={initialValues(project)}
          submitLabel="Save details"
          busy={update.isPending}
          serverError={update.error}
          onCancel={() => setEditing(false)}
          onSubmit={(payload) =>
            update.mutate(payload, {
              onSuccess: () => {
                setEditing(false);
                announce("Saved book details");
              },
            })
          }
        />
      </Dialog>
      <ConfirmDialog
        isOpen={confirmArchive}
        title={`Archive “${project.title}”?`}
        body="The book moves out of your active library and becomes read-only. Nothing is deleted, and you can unarchive it at any time."
        confirmLabel="Archive book"
        busy={setArchived.isPending}
        onCancel={() => setConfirmArchive(false)}
        onConfirm={() =>
          setArchived.mutate(true, {
            onSuccess: (p) => {
              setConfirmArchive(false);
              announce(`Archived “${p.title}”`);
            },
          })
        }
      />
    </>
  );
}

function ProjectActivity({ projectId }: { projectId: string }) {
  const activity = useActivity(projectId, 10);
  if (activity.isPending) return <Loading />;
  if (activity.isError) return <p className="muted">History could not be loaded.</p>;
  if (activity.data.length === 0) return <p className="muted">No changes yet.</p>;
  return <ActivityList items={activity.data} showProject={false} />;
}

const FORMAT_LABEL = {
  markdown: "Markdown",
  markdown_zip: "Markdown with images (ZIP)",
  html: "HTML",
} as const;

function ExportsSection({ project }: { project: Project }) {
  const exportsQuery = useExports(project.id);
  const create = useExportAs(project.id);
  const announce = useAnnounce();
  const id = useId();
  const latest = create.data;

  return (
    <section className="panel" aria-labelledby={`${id}-exports`}>
      <h2 id={`${id}-exports`}>Export</h2>
      <p className="muted" style={{ marginBottom: "var(--space-4)" }}>
        Every chapter in book order. Markdown keeps your exact text (images go in a ZIP alongside it); HTML is
        a single page with images included. EPUB, DOCX and print PDF arrive in Phase 07.
      </p>
      <div className="page-actions">
        {(["markdown", "html"] as const).map((fmt) => (
          <button
            key={fmt}
            type="button"
            className={fmt === "markdown" ? "btn btn-primary" : "btn"}
            disabled={create.isPending}
            onClick={() =>
              create.mutate(fmt, {
                onSuccess: (exp) => announce(`Exported ${FORMAT_LABEL[exp.format]}: ${exp.file_name ?? ""}`),
              })
            }
          >
            Export {fmt === "markdown" ? "Markdown" : "HTML"}
          </button>
        ))}
      </div>
      {create.isError ? <InlineError error={create.error} /> : null}
      {latest?.download_url ? (
        <p style={{ marginTop: "var(--space-3)" }}>
          <a href={latest.download_url} download={latest.file_name ?? true}>
            Download {latest.file_name}
          </a>
        </p>
      ) : null}
      {exportsQuery.data && exportsQuery.data.length > 0 ? (
        <>
          <h3 className="subhead">Earlier exports</h3>
          <ul className="exports">
            {exportsQuery.data.slice(0, 5).map((e) => (
              <li key={e.id}>
                {e.download_url ? (
                  <a href={e.download_url} download={e.file_name ?? true}>
                    {e.file_name}
                  </a>
                ) : (
                  e.file_name
                )}{" "}
                <span className="muted">
                  {FORMAT_LABEL[e.format]},{" "}
                  <time dateTime={e.started_at} title={absoluteTime(e.started_at)}>
                    {relativeTime(e.started_at)}
                  </time>
                  , {e.chapter_count === 1 ? "1 chapter" : `${e.chapter_count} chapters`}
                </span>
                {e.warnings.map((w) => (
                  <span className="warn block" key={w}>
                    {w}
                  </span>
                ))}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}

function BackupSection({ project }: { project: Project }) {
  const backups = useBackups(project.id);
  const create = useCreateBackup(project.id);
  const announce = useAnnounce();
  const id = useId();
  return (
    <section className="panel" aria-labelledby={`${id}-backup`}>
      <h2 id={`${id}-backup`}>Backup</h2>
      <p className="muted" style={{ marginBottom: "var(--space-4)" }}>
        One file with every chapter, every revision, images and original imports, with checksums. Restoring
        always creates a new book; it never replaces this one. Restore from the Library page.
      </p>
      <button
        type="button"
        className="btn"
        disabled={create.isPending}
        onClick={() =>
          create.mutate(undefined, { onSuccess: (b) => announce(`Backup created: ${b.file_name}`) })
        }
      >
        {create.isPending ? "Creating backup…" : "Create backup"}
      </button>
      {create.isError ? <InlineError error={create.error} /> : null}
      {backups.data && backups.data.length > 0 ? (
        <ul className="exports" style={{ marginTop: "var(--space-4)" }}>
          {backups.data.slice(0, 5).map((b) => (
            <li key={b.id}>
              <a href={b.download_url} download={b.file_name}>
                {b.file_name}
              </a>{" "}
              <span className="muted">
                <time dateTime={b.created_at} title={absoluteTime(b.created_at)}>
                  {relativeTime(b.created_at)}
                </time>
                , {(b.byte_size / 1024).toFixed(0)} KB
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
