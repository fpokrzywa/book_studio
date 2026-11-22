import { useId, useState, type CSSProperties, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import type { Chapter, Project } from "../../api/client";
import { ApiError } from "../../api/client";
import {
  useActivity,
  useArchiveChapter,
  useChapters,
  useCreateChapter,
  useCreateExport,
  useDuplicateProject,
  useExports,
  useProject,
  useSetArchived,
  useUpdateChapter,
  useUpdateProject,
} from "../../api/hooks";
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
  statusLabel,
  typeLabel,
  words,
} from "../../lib/format";
import { ActivityList } from "../activity/ActivityList";
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
        <ChaptersSection project={project} />
        <div className="stack">
          <ExportsSection project={project} />
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

function ChaptersSection({ project }: { project: Project }) {
  const chapters = useChapters(project.id);
  const create = useCreateChapter(project.id);
  const updateChapter = useUpdateChapter(project.id);
  const archiveChapter = useArchiveChapter(project.id);
  const announce = useAnnounce();
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [titleError, setTitleError] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<Chapter | null>(null);
  const [archiving, setArchiving] = useState<Chapter | null>(null);
  const id = useId();
  const readOnly = project.status === "archived";

  function addChapter(e: FormEvent) {
    e.preventDefault();
    if (!title.trim()) {
      setTitleError("Give the chapter a title.");
      return;
    }
    setTitleError(null);
    create.mutate(title.trim(), {
      onSuccess: (ch) => {
        setTitle("");
        announce(`Added chapter “${ch.title}”`);
        navigate(`/projects/${project.id}/chapters/${ch.id}`);
      },
    });
  }

  return (
    <section aria-labelledby={`${id}-chapters`}>
      <h2 id={`${id}-chapters`} style={{ marginBottom: "var(--space-4)" }}>
        Chapters
      </h2>
      {chapters.isPending ? (
        <Loading label="Loading chapters" />
      ) : chapters.isError ? (
        <ErrorState error={chapters.error} onRetry={() => void chapters.refetch()} />
      ) : chapters.data.length === 0 ? (
        <p className="muted" style={{ marginBottom: "var(--space-4)" }}>
          No chapters yet. Add the first one below; you can rename it any time.
        </p>
      ) : (
        <ol className="toc">
          {chapters.data.map((ch) => (
            <li key={ch.id}>
              <div>
                <Link to={`/projects/${project.id}/chapters/${ch.id}`}>{ch.title}</Link>
                <span className="meta">
                  {statusLabel(ch.status)}, {words(ch.word_count)}
                  {ch.head_revision_no > 0
                    ? `, saved ${relativeTime(ch.updated_at)} (revision ${ch.head_revision_no})`
                    : ", not saved yet"}
                </span>
              </div>
              <div className="row-actions">
                <button
                  type="button"
                  className="btn btn-small btn-quiet"
                  disabled={readOnly}
                  onClick={() => setRenaming(ch)}
                  aria-label={`Rename ${ch.title}`}
                >
                  Rename
                </button>
                <button
                  type="button"
                  className="btn btn-small btn-quiet"
                  disabled={readOnly}
                  onClick={() => setArchiving(ch)}
                  aria-label={`Archive ${ch.title}`}
                >
                  Archive
                </button>
              </div>
            </li>
          ))}
        </ol>
      )}
      {!readOnly ? (
        <form className="add-chapter" onSubmit={addChapter} noValidate>
          <div className="field">
            <label htmlFor={`${id}-new`}>New chapter title</label>
            <input
              id={`${id}-new`}
              type="text"
              value={title}
              maxLength={300}
              aria-invalid={titleError ? true : undefined}
              aria-describedby={titleError ? `${id}-new-error` : undefined}
              onChange={(e) => setTitle(e.target.value)}
            />
            {titleError ? (
              <span className="error" id={`${id}-new-error`}>
                {titleError}
              </span>
            ) : null}
          </div>
          <button type="submit" className="btn btn-primary" disabled={create.isPending}>
            Add chapter
          </button>
        </form>
      ) : null}
      {create.isError ? <InlineError error={create.error} /> : null}

      <RenameDialog
        chapter={renaming}
        busy={updateChapter.isPending}
        error={updateChapter.error}
        onClose={() => {
          setRenaming(null);
          updateChapter.reset();
        }}
        onSave={(cid, newTitle) =>
          updateChapter.mutate(
            { cid, title: newTitle },
            {
              onSuccess: (ch) => {
                setRenaming(null);
                announce(`Renamed chapter to “${ch.title}”`);
              },
            },
          )
        }
      />
      <ConfirmDialog
        isOpen={archiving !== null}
        title={`Archive chapter “${archiving?.title ?? ""}”?`}
        body="The chapter is removed from the table of contents and from exports. Its saved revisions are kept in the database."
        confirmLabel="Archive chapter"
        busy={archiveChapter.isPending}
        onCancel={() => setArchiving(null)}
        onConfirm={() =>
          archiving &&
          archiveChapter.mutate(archiving.id, {
            onSuccess: () => {
              announce(`Archived chapter “${archiving.title}”`);
              setArchiving(null);
            },
          })
        }
      />
    </section>
  );
}

function RenameDialog({
  chapter,
  busy,
  error,
  onClose,
  onSave,
}: {
  chapter: Chapter | null;
  busy: boolean;
  error: unknown;
  onClose: () => void;
  onSave: (cid: string, title: string) => void;
}) {
  const [value, setValue] = useState("");
  const [lastId, setLastId] = useState<string | null>(null);
  const id = useId();
  if (chapter && chapter.id !== lastId) {
    setLastId(chapter.id);
    setValue(chapter.title);
  }
  return (
    <Dialog isOpen={chapter !== null} onClose={onClose} title="Rename chapter">
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          if (chapter && value.trim()) onSave(chapter.id, value.trim());
        }}
      >
        {error ? <InlineError error={error} /> : null}
        <div className="field">
          <label htmlFor={`${id}-title`}>Chapter title</label>
          <input
            id={`${id}-title`}
            type="text"
            value={value}
            maxLength={300}
            onChange={(e) => setValue(e.target.value)}
          />
        </div>
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy || !value.trim()}>
            Rename
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function ExportsSection({ project }: { project: Project }) {
  const exportsQuery = useExports(project.id);
  const create = useCreateExport(project.id);
  const announce = useAnnounce();
  const id = useId();
  const latest = create.data;

  return (
    <section className="panel" aria-labelledby={`${id}-exports`}>
      <h2 id={`${id}-exports`}>Export</h2>
      <p className="muted" style={{ marginBottom: "var(--space-4)" }}>
        Markdown export puts every chapter, in order, into one file with its exact text. EPUB, DOCX and print
        PDF arrive in Phase 07.
      </p>
      <button
        type="button"
        className="btn btn-primary"
        disabled={create.isPending}
        onClick={() =>
          create.mutate(undefined, {
            onSuccess: (exp) => announce(`Exported Markdown: ${exp.file_name ?? ""}`),
          })
        }
      >
        {create.isPending ? "Exporting…" : "Export Markdown"}
      </button>
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
          <h3 style={{ margin: "var(--space-5) 0 var(--space-3)", fontSize: "var(--step-0)" }}>
            Earlier exports
          </h3>
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
                  <time dateTime={e.started_at} title={absoluteTime(e.started_at)}>
                    {relativeTime(e.started_at)}
                  </time>
                  , {e.chapter_count === 1 ? "1 chapter" : `${e.chapter_count} chapters`}
                </span>
                {e.warnings.map((w) => (
                  <span className="warn" key={w} style={{ display: "block" }}>
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
