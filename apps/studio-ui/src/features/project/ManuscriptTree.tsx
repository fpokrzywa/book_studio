import { useId, useState, type DragEvent, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import type { Project } from "../../api/client";
import { useArchiveChapter, useChapters } from "../../api/hooks";
import type { Chapter } from "../../api/manuscript";
import { useCreateSection, useMoveChapter, usePatchChapter } from "../../api/manuscript";
import { useAnnounce } from "../../components/Announcer";
import { ConfirmDialog, Dialog } from "../../components/Dialog";
import { ErrorState, InlineError, Loading } from "../../components/States";
import { CHAPTER_STATUSES, n, relativeTime, statusLabel, words } from "../../lib/format";

const MAX_DEPTH = 2;
const KIND_LABEL: Record<Chapter["kind"], string> = {
  part: "Part",
  chapter: "Chapter",
  section: "Section",
  front_matter: "Front matter",
  back_matter: "Back matter",
};

function siblingsOf(items: Chapter[], parentId: string | null): Chapter[] {
  return items.filter((c) => c.parent_id === parentId);
}

function subtreeHeight(items: Chapter[], id: string): number {
  const kids = items.filter((c) => c.parent_id === id);
  return kids.length ? 1 + Math.max(...kids.map((k) => subtreeHeight(items, k.id))) : 0;
}

/**
 * The book's canonical chapter order. Reordering changes only position and parent: chapter IDs,
 * revisions, images and citation keys are untouched, so nothing can be orphaned.
 * Every drag action has a button equivalent (Move up/down, Indent, Outdent) for keyboard users.
 */
export function ManuscriptTree({ project }: { project: Project }) {
  const chapters = useChapters(project.id);
  const move = useMoveChapter(project.id);
  const create = useCreateSection(project.id);
  const archive = useArchiveChapter(project.id);
  const announce = useAnnounce();
  const navigate = useNavigate();
  const id = useId();
  const [title, setTitle] = useState("");
  const [parent, setParent] = useState<string>("");
  const [titleError, setTitleError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Chapter | null>(null);
  const [archiving, setArchiving] = useState<Chapter | null>(null);
  const [dragId, setDragId] = useState<string | null>(null);
  const [dropHint, setDropHint] = useState<{ id: string; where: "before" | "after" } | null>(null);
  const readOnly = project.status === "archived";

  if (chapters.isPending) return <Loading label="Loading chapters" />;
  if (chapters.isError) return <ErrorState error={chapters.error} onRetry={() => void chapters.refetch()} />;
  const items = chapters.data;
  const totalWords = items.reduce((sum, c) => sum + c.word_count, 0);

  function doMove(ch: Chapter, parentId: string | null, index: number, message: string) {
    move.mutate({ cid: ch.id, parentId, index }, { onSuccess: () => announce(message) });
  }

  function onDrop(e: DragEvent, target: Chapter) {
    e.preventDefault();
    const moving = items.find((c) => c.id === (dragId ?? e.dataTransfer.getData("text/plain")));
    setDragId(null);
    setDropHint(null);
    if (!moving || moving.id === target.id) return;
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const after = e.clientY > rect.top + rect.height / 2;
    const sibs = siblingsOf(items, target.parent_id).filter((c) => c.id !== moving.id);
    const index = sibs.findIndex((c) => c.id === target.id) + (after ? 1 : 0);
    doMove(
      moving,
      target.parent_id,
      index,
      `Moved “${moving.title}” ${after ? "after" : "before"} “${target.title}”`,
    );
  }

  function addChapter(e: FormEvent) {
    e.preventDefault();
    if (!title.trim()) return setTitleError("Give the chapter a title.");
    setTitleError(null);
    const parentChapter = items.find((c) => c.id === parent);
    create.mutate(
      {
        title: title.trim(),
        parent_id: parent || null,
        kind: parentChapter ? (parentChapter.kind === "part" ? "chapter" : "section") : "chapter",
      },
      {
        onSuccess: (ch) => {
          setTitle("");
          announce(`Added “${ch.title}”`);
          navigate(`/projects/${project.id}/chapters/${ch.id}`);
        },
      },
    );
  }

  return (
    <section aria-labelledby={`${id}-toc`}>
      <div className="section-head">
        <h2 id={`${id}-toc`}>Manuscript</h2>
        <p className="muted">
          {items.length === 1 ? "1 chapter" : `${n(items.length)} chapters`}, {words(totalWords)}
        </p>
      </div>
      {items.length === 0 ? (
        <p className="muted" style={{ marginBottom: "var(--space-4)" }}>
          No chapters yet. Add the first one below, or import an existing manuscript.
        </p>
      ) : (
        <>
          <p className="muted hint-line" id={`${id}-dnd`}>
            Drag a chapter to reorder it, or use its Move and Indent buttons.
          </p>
          <ol className="tree" aria-describedby={`${id}-dnd`}>
            {items.map((ch) => {
              const sibs = siblingsOf(items, ch.parent_id);
              const pos = sibs.findIndex((c) => c.id === ch.id);
              const prev = pos > 0 ? sibs[pos - 1] : undefined;
              const parentCh = items.find((c) => c.id === ch.parent_id);
              const canIndent = !!prev && ch.depth + 1 + subtreeHeight(items, ch.id) <= MAX_DEPTH;
              const progress = ch.target_word_count
                ? Math.min(1, ch.word_count / ch.target_word_count)
                : null;
              return (
                // Drag-and-drop is a mouse shortcut; the Up/Down/Indent/Outdent buttons are the keyboard path.
                // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
                <li
                  key={ch.id}
                  className="tree-row"
                  data-depth={ch.depth}
                  data-drop={dropHint?.id === ch.id ? dropHint.where : undefined}
                  style={{ marginLeft: `${ch.depth * 1.75}rem` }}
                  draggable={!readOnly}
                  onDragStart={(e) => {
                    setDragId(ch.id);
                    e.dataTransfer.setData("text/plain", ch.id);
                    e.dataTransfer.effectAllowed = "move";
                  }}
                  onDragEnd={() => {
                    setDragId(null);
                    setDropHint(null);
                  }}
                  onDragOver={(e) => {
                    if (!dragId || dragId === ch.id) return;
                    e.preventDefault();
                    const rect = e.currentTarget.getBoundingClientRect();
                    setDropHint({
                      id: ch.id,
                      where: e.clientY > rect.top + rect.height / 2 ? "after" : "before",
                    });
                  }}
                  onDragLeave={() => setDropHint(null)}
                  onDrop={(e) => onDrop(e, ch)}
                >
                  <span className="grip" aria-hidden="true">
                    ⋮⋮
                  </span>
                  <div className="tree-main">
                    <Link to={`/projects/${project.id}/chapters/${ch.id}`}>{ch.title}</Link>
                    <span className="meta">
                      {KIND_LABEL[ch.kind]}, {statusLabel(ch.status)}, {words(ch.word_count)}
                      {ch.target_word_count ? ` of ${n(ch.target_word_count)}` : ""}
                      {ch.head_revision_no > 0
                        ? `, revision ${ch.head_revision_no} saved ${relativeTime(ch.updated_at)}`
                        : ", not saved yet"}
                    </span>
                    {progress !== null ? (
                      <span
                        className="bar"
                        role="img"
                        aria-label={`${Math.round(progress * 100)}% of target length`}
                      >
                        <span style={{ width: `${Math.max(2, progress * 100)}%` }} />
                      </span>
                    ) : null}
                  </div>
                  <div className="row-actions" role="group" aria-label={`Arrange ${ch.title}`}>
                    <button
                      type="button"
                      className="btn btn-small btn-quiet"
                      disabled={readOnly || pos <= 0 || move.isPending}
                      onClick={() => doMove(ch, ch.parent_id, pos - 1, `Moved “${ch.title}” up`)}
                      aria-label={`Move ${ch.title} up`}
                    >
                      Up
                    </button>
                    <button
                      type="button"
                      className="btn btn-small btn-quiet"
                      disabled={readOnly || pos >= sibs.length - 1 || move.isPending}
                      onClick={() => doMove(ch, ch.parent_id, pos + 1, `Moved “${ch.title}” down`)}
                      aria-label={`Move ${ch.title} down`}
                    >
                      Down
                    </button>
                    <button
                      type="button"
                      className="btn btn-small btn-quiet"
                      disabled={readOnly || !canIndent || move.isPending}
                      onClick={() =>
                        prev &&
                        doMove(
                          ch,
                          prev.id,
                          siblingsOf(items, prev.id).length,
                          `“${ch.title}” is now inside “${prev.title}”`,
                        )
                      }
                      aria-label={`Indent ${ch.title} under the previous chapter`}
                    >
                      Indent
                    </button>
                    <button
                      type="button"
                      className="btn btn-small btn-quiet"
                      disabled={readOnly || !parentCh || move.isPending}
                      onClick={() => {
                        if (!parentCh) return;
                        const outer = siblingsOf(items, parentCh.parent_id);
                        doMove(
                          ch,
                          parentCh.parent_id,
                          outer.findIndex((c) => c.id === parentCh.id) + 1,
                          `Moved “${ch.title}” out of “${parentCh.title}”`,
                        );
                      }}
                      aria-label={`Outdent ${ch.title}`}
                    >
                      Outdent
                    </button>
                    <button
                      type="button"
                      className="btn btn-small btn-quiet"
                      disabled={readOnly}
                      onClick={() => setEditing(ch)}
                      aria-label={`Edit details of ${ch.title}`}
                    >
                      Details
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
              );
            })}
          </ol>
        </>
      )}
      {move.isError ? <InlineError error={move.error} /> : null}

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
          {items.length > 0 ? (
            <div className="field">
              <label htmlFor={`${id}-parent`}>Place in</label>
              <select id={`${id}-parent`} value={parent} onChange={(e) => setParent(e.target.value)}>
                <option value="">Top level</option>
                {items
                  .filter((c) => c.depth < MAX_DEPTH)
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {"— ".repeat(c.depth)}
                      {c.title}
                    </option>
                  ))}
              </select>
            </div>
          ) : null}
          <button type="submit" className="btn btn-primary" disabled={create.isPending}>
            Add chapter
          </button>
        </form>
      ) : null}
      {create.isError ? <InlineError error={create.error} /> : null}

      <ChapterDetailsDialog chapter={editing} projectId={project.id} onClose={() => setEditing(null)} />
      <ConfirmDialog
        isOpen={archiving !== null}
        title={`Archive “${archiving?.title ?? ""}”?`}
        body="The chapter and any sections inside it leave the table of contents and exports. Their saved revisions are kept."
        confirmLabel="Archive chapter"
        busy={archive.isPending}
        onCancel={() => setArchiving(null)}
        onConfirm={() =>
          archiving &&
          archive.mutate(archiving.id, {
            onSuccess: () => {
              announce(`Archived “${archiving.title}”`);
              setArchiving(null);
            },
          })
        }
      />
    </section>
  );
}

function ChapterDetailsDialog({
  chapter,
  projectId,
  onClose,
}: {
  chapter: Chapter | null;
  projectId: string;
  onClose: () => void;
}) {
  const id = useId();
  const patch = usePatchChapter(projectId);
  const announce = useAnnounce();
  const [current, setCurrent] = useState<string | null>(null);
  const [form, setForm] = useState({ title: "", slug: "", status: "draft", target: "" });
  const [error, setError] = useState<string | null>(null);
  if (chapter && chapter.id !== current) {
    setCurrent(chapter.id);
    setForm({
      title: chapter.title,
      slug: chapter.slug,
      status: chapter.status,
      target: chapter.target_word_count != null ? String(chapter.target_word_count) : "",
    });
    setError(null);
    patch.reset();
  }
  const close = () => {
    setCurrent(null);
    onClose();
  };
  return (
    <Dialog isOpen={chapter !== null} onClose={close} title="Chapter details">
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          if (!chapter) return;
          if (!form.title.trim()) return setError("The title cannot be empty.");
          if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(form.slug))
            return setError(
              "Use lowercase letters, numbers and single hyphens in the slug, for example getting-started.",
            );
          const target = form.target.trim() ? Number(form.target) : null;
          if (target !== null && (!Number.isInteger(target) || target < 0))
            return setError("Enter a whole number of words, or leave the target empty.");
          setError(null);
          patch.mutate(
            {
              cid: chapter.id,
              title: form.title.trim(),
              slug: form.slug,
              status: form.status as Chapter["status"],
              target_word_count: target,
            },
            {
              onSuccess: (ch) => {
                announce(`Saved details of “${ch.title}”`);
                close();
              },
            },
          );
        }}
      >
        {error ? (
          <p className="error" role="alert">
            {error}
          </p>
        ) : null}
        {patch.isError ? <InlineError error={patch.error} /> : null}
        <div className="field">
          <label htmlFor={`${id}-title`}>Title</label>
          <input
            id={`${id}-title`}
            type="text"
            maxLength={300}
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
          />
        </div>
        <div className="field">
          <label htmlFor={`${id}-slug`}>Slug</label>
          <input
            id={`${id}-slug`}
            type="text"
            maxLength={80}
            value={form.slug}
            aria-describedby={`${id}-slug-hint`}
            onChange={(e) => setForm({ ...form, slug: e.target.value })}
          />
          <span className="hint" id={`${id}-slug-hint`}>
            Used for the chapter&apos;s link anchor (#ch-{form.slug || "…"}) in exports.
          </span>
        </div>
        <div className="form-row">
          <div className="field">
            <label htmlFor={`${id}-status`}>Status</label>
            <select
              id={`${id}-status`}
              value={form.status}
              onChange={(e) => setForm({ ...form, status: e.target.value })}
            >
              {CHAPTER_STATUSES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor={`${id}-target`}>Target length in words</label>
            <input
              id={`${id}-target`}
              type="number"
              min={0}
              step={500}
              value={form.target}
              onChange={(e) => setForm({ ...form, target: e.target.value })}
            />
          </div>
        </div>
        <div className="modal-actions">
          <button type="button" className="btn" onClick={close}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={patch.isPending}>
            Save details
          </button>
        </div>
      </form>
    </Dialog>
  );
}
