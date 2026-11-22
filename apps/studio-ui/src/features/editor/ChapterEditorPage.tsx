import { useCallback, useEffect, useId, useState, type KeyboardEvent } from "react";
import { Link, useBlocker, useParams } from "react-router";
import type { ChapterContent, ChapterStatus } from "../../api/client";
import { ApiError } from "../../api/client";
import { useChapter, useChapterContent, useProject, useSaveContent, useUpdateChapter } from "../../api/hooks";
import { useAnnounce } from "../../components/Announcer";
import { ConfirmDialog, Dialog } from "../../components/Dialog";
import { usePageTitle } from "../../components/Misc";
import { EmptyState, ErrorState, InlineError, Loading } from "../../components/States";
import { absoluteTime, CHAPTER_STATUSES, relativeTime, words } from "../../lib/format";

export function ChapterEditorPage() {
  const { projectId = "", chapterId = "" } = useParams();
  const project = useProject(projectId);
  const chapter = useChapter(projectId, chapterId);
  const content = useChapterContent(projectId, chapterId);

  const failed = [project, chapter, content].find((q) => q.isError);
  if (failed?.error) {
    if (failed.error instanceof ApiError && failed.error.status === 404) {
      return (
        <EmptyState
          title="Chapter not found"
          action={<Link to={projectId ? `/projects/${projectId}` : "/"}>Back to the book</Link>}
        >
          This chapter does not exist in this book. It may have been archived, or the address may belong to a
          different book.
        </EmptyState>
      );
    }
    return <ErrorState error={failed.error} onRetry={() => void content.refetch()} />;
  }
  if (!project.data || !chapter.data || !content.data) return <Loading label="Opening the chapter" />;

  return (
    <Editor
      key={chapterId}
      projectId={projectId}
      projectTitle={project.data.title}
      readOnly={project.data.status === "archived"}
      chapterId={chapterId}
      chapterTitle={chapter.data.title}
      status={chapter.data.status}
      initial={content.data}
    />
  );
}

interface EditorProps {
  projectId: string;
  projectTitle: string;
  readOnly: boolean;
  chapterId: string;
  chapterTitle: string;
  status: ChapterStatus;
  initial: ChapterContent;
}

function Editor({
  projectId,
  projectTitle,
  readOnly,
  chapterId,
  chapterTitle,
  status,
  initial,
}: EditorProps) {
  usePageTitle(chapterTitle);
  const id = useId();
  const announce = useAnnounce();
  const save = useSaveContent(projectId, chapterId);
  const updateChapter = useUpdateChapter(projectId);
  const [base, setBase] = useState<ChapterContent>(initial);
  const [text, setText] = useState(initial.source_md);
  const [conflict, setConflict] = useState<ChapterContent | null>(null);
  const dirty = text !== base.source_md;
  const approved = status === "approved";

  const doSave = useCallback(
    (expected: number) => {
      if (readOnly || save.isPending) return;
      save.mutate(
        { source_md: text, expected_head_no: expected },
        {
          onSuccess: (result) => {
            setBase(result.content);
            setConflict(null);
            announce(result.created ? `Saved revision ${result.content.revision_no}` : "No changes to save");
          },
          onError: (err) => {
            if (err instanceof ApiError && err.code === "conflict" && err.problem.current) {
              setConflict(err.problem.current as ChapterContent);
            }
          },
        },
      );
    },
    [announce, readOnly, save, text],
  );

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      doSave(base.revision_no);
    }
  };

  // Warn before closing the tab with unsaved text.
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  // Ask before navigating away inside the app with unsaved text.
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname,
  );

  const saveError = save.error instanceof ApiError && save.error.code === "conflict" ? null : save.error;
  const approvedError =
    save.error instanceof ApiError && save.error.problem.reason === "chapter_approved" ? save.error : null;

  return (
    <div className="manuscript">
      <div className="editor-bar">
        <nav className="crumbs" aria-label="Breadcrumb">
          <Link to={`/projects/${projectId}`}>{projectTitle}</Link>
        </nav>
        <div className="editor-tools">
          <div className="field" style={{ gridAutoFlow: "column", alignItems: "center" }}>
            <label htmlFor={`${id}-status`} style={{ fontSize: "var(--step--1)" }}>
              Status
            </label>
            <select
              id={`${id}-status`}
              value={status}
              disabled={readOnly || updateChapter.isPending}
              onChange={(e) =>
                updateChapter.mutate(
                  { cid: chapterId, status: e.target.value as ChapterStatus },
                  { onSuccess: (ch) => announce(`Status set to ${ch.status.replace("_", " ")}`) },
                )
              }
              style={{ width: "auto", minHeight: "2rem" }}
            >
              {CHAPTER_STATUSES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          <span className="save-state" data-dirty={dirty} aria-live="off">
            {dirty
              ? "Unsaved changes"
              : base.revision_no === 0
                ? "Not saved yet"
                : `Saved as revision ${base.revision_no}`}
            {!dirty && base.saved_at ? (
              <>
                {" "}
                <time dateTime={base.saved_at} title={absoluteTime(base.saved_at)}>
                  {relativeTime(base.saved_at)}
                </time>
              </>
            ) : null}
          </span>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => doSave(base.revision_no)}
            disabled={readOnly || approved || save.isPending || !dirty}
            aria-keyshortcuts="Control+S Meta+S"
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      <h1 id={`${id}-title`}>{chapterTitle}</h1>

      {readOnly ? (
        <div className="banner" role="note">
          This book is archived, so the chapter is read-only. Unarchive the book to edit.
        </div>
      ) : null}
      {approved && !readOnly ? (
        <div className="banner" role="note">
          <span>This chapter is approved, so it is locked against edits.</span>
          <button
            type="button"
            className="btn btn-small"
            onClick={() => updateChapter.mutate({ cid: chapterId, status: "in_review" })}
          >
            Reopen for editing
          </button>
        </div>
      ) : null}
      {approvedError ? <InlineError error={approvedError} /> : null}
      {saveError && !approvedError ? (
        <InlineError error={saveError}>
          <button type="button" className="btn btn-small" onClick={() => doSave(base.revision_no)}>
            Try saving again
          </button>
        </InlineError>
      ) : null}

      <label htmlFor={`${id}-text`} className="visually-hidden">
        Chapter text (Markdown)
      </label>
      <textarea
        id={`${id}-text`}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        readOnly={readOnly || approved}
        spellCheck
        aria-describedby={`${id}-hint`}
      />
      <p className="hint" id={`${id}-hint`}>
        {words(countWords(text))}. Write in Markdown; your text is stored exactly as typed. Every save keeps a
        new revision, so earlier versions are never overwritten. Press Ctrl+S (Cmd+S on a Mac) to save.
      </p>

      <Dialog
        isOpen={conflict !== null}
        onClose={() => setConflict(null)}
        title="This chapter changed somewhere else"
        role="alertdialog"
      >
        <p>
          A newer version (revision {conflict?.revision_no}) was saved after you opened this chapter, probably
          in another window. Choose which text to keep. Both stay in the revision history either way.
        </p>
        <div className="modal-actions">
          <button
            type="button"
            className="btn"
            onClick={() => {
              if (conflict) {
                setBase(conflict);
                setText(conflict.source_md);
                setConflict(null);
                announce(`Loaded revision ${conflict.revision_no}`);
              }
            }}
          >
            Load the newer version
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => conflict && doSave(conflict.revision_no)}
          >
            Save my text as the newest revision
          </button>
        </div>
      </Dialog>

      <ConfirmDialog
        isOpen={blocker.state === "blocked"}
        title="Leave without saving?"
        body="Your latest changes to this chapter are not saved yet."
        confirmLabel="Leave and discard changes"
        cancelLabel="Stay on this chapter"
        danger
        onCancel={() => blocker.reset?.()}
        onConfirm={() => blocker.proceed?.()}
      />
    </div>
  );
}

function countWords(text: string): number {
  const stripped = text.replace(/```[\s\S]*?```/g, " ");
  return (stripped.match(/[\p{L}\p{N}_][\p{L}\p{N}_'’-]*/gu) ?? []).length;
}
