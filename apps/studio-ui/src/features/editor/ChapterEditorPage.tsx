import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Link, useBlocker, useParams } from "react-router";
import type { ChapterContent, ChapterStatus } from "../../api/client";
import { ApiError } from "../../api/client";
import {
  useChapter,
  useChapterContent,
  useChapters,
  useProject,
  useSaveContent,
  useUpdateChapter,
} from "../../api/hooks";
import type { Preview } from "../../api/manuscript";
import { useDiscardDraft, usePreview, useSaveDraft, useUploadAsset } from "../../api/manuscript";
import { useAnnounce } from "../../components/Announcer";
import { Dialog } from "../../components/Dialog";
import { usePageTitle } from "../../components/Misc";
import { SanitizedHtml } from "../../components/SanitizedHtml";
import { EmptyState, ErrorState, InlineError, Loading } from "../../components/States";
import { absoluteTime, CHAPTER_STATUSES, relativeTime, words } from "../../lib/format";
import { useProposals } from "../../api/ai";
import { AiAssistPanel } from "../ai/AiAssistPanel";
import { HistoryPanel } from "./HistoryPanel";
import { SourceEditor, type SourceEditorHandle } from "./SourceEditor";

const AUTOSAVE_MS = 1500;
const PREVIEW_MS = 450;
type View = "write" | "split" | "preview";

function stored<T extends string>(key: string, fallback: T, allowed: readonly T[]): T {
  try {
    const v = localStorage.getItem(key) as T | null;
    return v && allowed.includes(v) ? v : fallback;
  } catch {
    return fallback;
  }
}

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
    <div className="editor-layout">
      <ChapterNav projectId={projectId} currentId={chapterId} />
      <Editor
        key={chapterId}
        projectId={projectId}
        projectTitle={project.data.title}
        readOnly={project.data.status === "archived"}
        chapterId={chapterId}
        chapterTitle={chapter.data.title}
        status={chapter.data.status}
        aiLocked={chapter.data.locked}
        initial={content.data}
      />
    </div>
  );
}

function ChapterNav({ projectId, currentId }: { projectId: string; currentId: string }) {
  const chapters = useChapters(projectId);
  const items = chapters.data ?? [];
  const index = items.findIndex((c) => c.id === currentId);
  const prev = index > 0 ? items[index - 1] : undefined;
  const next = index >= 0 && index < items.length - 1 ? items[index + 1] : undefined;
  return (
    <nav className="chapter-nav" aria-label="Chapters in this book">
      <ol>
        {items.map((c) => (
          <li key={c.id} style={{ paddingLeft: `${c.depth * 0.9}rem` }}>
            <Link
              to={`/projects/${projectId}/chapters/${c.id}`}
              aria-current={c.id === currentId ? "page" : undefined}
            >
              {c.title}
            </Link>
          </li>
        ))}
      </ol>
      <div className="prev-next">
        {prev ? (
          <Link to={`/projects/${projectId}/chapters/${prev.id}`} rel="prev">
            Previous: {prev.title}
          </Link>
        ) : null}
        {next ? (
          <Link to={`/projects/${projectId}/chapters/${next.id}`} rel="next">
            Next: {next.title}
          </Link>
        ) : null}
      </div>
    </nav>
  );
}

interface EditorProps {
  projectId: string;
  projectTitle: string;
  readOnly: boolean;
  chapterId: string;
  chapterTitle: string;
  status: ChapterStatus;
  aiLocked: boolean;
  initial: ChapterContent;
}

type DraftNotice = { kind: "recovered" | "stale"; at: string; baseNo: number } | null;

function Editor({
  projectId,
  projectTitle,
  readOnly,
  chapterId,
  chapterTitle,
  status,
  aiLocked,
  initial,
}: EditorProps) {
  usePageTitle(chapterTitle);
  const id = useId();
  const announce = useAnnounce();
  const save = useSaveContent(projectId, chapterId);
  const saveDraft = useSaveDraft(projectId, chapterId);
  const discardDraft = useDiscardDraft(projectId, chapterId);
  const updateChapter = useUpdateChapter(projectId);
  const preview = usePreview(projectId);
  const editor = useRef<SourceEditorHandle>(null);

  const draftMatches = initial.draft != null && initial.draft.base_revision_no === initial.revision_no;
  const [base, setBase] = useState<ChapterContent>(initial);
  const [text, setText] = useState(
    draftMatches && initial.draft ? initial.draft.source_md : initial.source_md,
  );
  // Text already safe on disk (a revision or an autosaved draft).
  const [persisted, setPersisted] = useState(
    draftMatches && initial.draft ? initial.draft.source_md : initial.source_md,
  );
  const [draftAt, setDraftAt] = useState<string | null>(
    draftMatches && initial.draft ? initial.draft.updated_at : null,
  );
  const [notice, setNotice] = useState<DraftNotice>(
    initial.draft
      ? {
          kind: draftMatches ? "recovered" : "stale",
          at: initial.draft.updated_at,
          baseNo: initial.draft.base_revision_no,
        }
      : null,
  );
  const [conflict, setConflict] = useState<ChapterContent | null>(null);
  const [view, setView] = useState<View>(() =>
    stored("pbs.editor.view", "split", ["write", "split", "preview"] as const),
  );
  const [plain, setPlain] = useState(
    () => stored("pbs.editor.mode", "code", ["code", "plain"] as const) === "plain",
  );
  const [historyOpen, setHistoryOpen] = useState(false);
  const [aiOpen, setAiOpen] = useState(
    () => stored("pbs.editor.ai", "closed", ["open", "closed"] as const) === "open",
  );
  const proposals = useProposals(projectId, chapterId);
  const pendingCount = proposals.data?.length ?? 0;
  const setAiOpenStored = (open: boolean) => {
    setAiOpen(open);
    try {
      localStorage.setItem("pbs.editor.ai", open ? "open" : "closed");
    } catch {
      /* ignore */
    }
  };
  const [imageOpen, setImageOpen] = useState(false);
  const [rendered, setRendered] = useState<Preview | null>(null);

  const approved = status === "approved";
  const locked = readOnly || approved;
  const dirty = text !== base.source_md;
  const pending = text !== persisted;

  const handleConflict = useCallback((err: unknown) => {
    if (err instanceof ApiError && err.code === "conflict" && err.problem.current) {
      setConflict(err.problem.current as ChapterContent);
      return true;
    }
    return false;
  }, []);

  // ----- autosave (draft, not a revision) -----
  useEffect(() => {
    if (locked || !pending || conflict) return;
    const t = setTimeout(() => {
      const snapshot = text;
      saveDraft.mutate(
        { source_md: snapshot, base_revision_no: base.revision_no },
        {
          onSuccess: (res) => {
            setPersisted(snapshot);
            setDraftAt(res.draft?.updated_at ?? null);
          },
          onError: handleConflict,
        },
      );
    }, AUTOSAVE_MS);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, pending, locked, conflict, base.revision_no]);

  // ----- live preview -----
  const previewVisible = view !== "write";
  useEffect(() => {
    if (!previewVisible) return;
    const t = setTimeout(() => preview.mutate(text, { onSuccess: setRendered }), PREVIEW_MS);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, previewVisible]);

  const doSave = useCallback(
    (expected: number, onDone?: () => void) => {
      if (locked || save.isPending) return;
      const snapshot = text;
      save.mutate(
        { source_md: snapshot, expected_head_no: expected },
        {
          onSuccess: (result) => {
            setBase(result.content);
            setPersisted(snapshot);
            setDraftAt(null);
            setNotice(null);
            setConflict(null);
            announce(result.created ? `Saved revision ${result.content.revision_no}` : "No changes to save");
            onDone?.();
          },
          onError: handleConflict,
        },
      );
    },
    [announce, handleConflict, locked, save, text],
  );

  // History restores update the cached content; follow them into the editor (derived during render).
  const [seenRevision, setSeenRevision] = useState(initial.revision_no);
  if (initial.revision_no !== seenRevision) {
    setSeenRevision(initial.revision_no);
    if (initial.revision_no > base.revision_no && !pending) {
      setBase(initial);
      setText(initial.source_md);
      setPersisted(initial.source_md);
    }
  }

  // Leaving the page: nothing is lost once the autosave has landed; ask only while it is pending.
  useEffect(() => {
    if (!pending) return;
    const handler = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [pending]);
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      pending && !locked && currentLocation.pathname !== nextLocation.pathname,
  );

  const setViewStored = (v: View) => {
    setView(v);
    try {
      localStorage.setItem("pbs.editor.view", v);
    } catch {
      /* storage unavailable: preference is just not remembered */
    }
  };
  const setPlainStored = (p: boolean) => {
    setPlain(p);
    try {
      localStorage.setItem("pbs.editor.mode", p ? "plain" : "code");
    } catch {
      /* ignore */
    }
  };

  const saveError =
    save.error instanceof ApiError &&
    (save.error.code === "conflict" || save.error.problem.reason === "chapter_approved")
      ? null
      : save.error;
  const approvedError =
    save.error instanceof ApiError && save.error.problem.reason === "chapter_approved" ? save.error : null;
  const wordCount = rendered?.word_count ?? null;

  let state: string;
  if (readOnly) state = "Read-only";
  else if (saveDraft.isPending || (pending && !conflict)) state = "Unsaved changes, autosaving…";
  else if (dirty)
    state = draftAt ? `Draft autosaved ${relativeTime(draftAt)}, not yet a revision` : "Unsaved changes";
  else state = base.revision_no === 0 ? "Not saved yet" : `Saved as revision ${base.revision_no}`;

  return (
    <div className="manuscript">
      <div className="editor-bar">
        <nav className="crumbs" aria-label="Breadcrumb">
          <Link to={`/projects/${projectId}`}>{projectTitle}</Link>
        </nav>
        <div className="editor-tools">
          <div className="field inline-field">
            <label htmlFor={`${id}-status`}>Status</label>
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
            >
              {CHAPTER_STATUSES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          <label className="inline-check">
            <input
              type="checkbox"
              checked={aiLocked}
              disabled={readOnly || updateChapter.isPending}
              onChange={(e) =>
                updateChapter.mutate(
                  { cid: chapterId, locked: e.target.checked },
                  {
                    onSuccess: (ch) =>
                      announce(ch.locked ? "Locked against AI changes" : "AI suggestions allowed again"),
                  },
                )
              }
            />
            Lock against AI changes
          </label>
          <span className="save-state" data-dirty={dirty} aria-live="off">
            {state}
            {!dirty && base.saved_at ? (
              <>
                {" "}
                <time dateTime={base.saved_at} title={absoluteTime(base.saved_at)}>
                  {relativeTime(base.saved_at)}
                </time>
              </>
            ) : null}
          </span>
          <button type="button" className="btn" onClick={() => setHistoryOpen(true)}>
            History
          </button>
          <button
            type="button"
            className="btn"
            aria-expanded={aiOpen}
            aria-controls={`${id}-ai`}
            onClick={() => setAiOpenStored(!aiOpen)}
          >
            AI assist{pendingCount ? ` (${pendingCount} to review)` : ""}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => doSave(base.revision_no)}
            disabled={locked || save.isPending || !dirty}
            aria-keyshortcuts="Control+S Meta+S"
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      <h1>{chapterTitle}</h1>

      {notice?.kind === "recovered" ? (
        <div className="banner" role="status">
          <span>
            Recovered unsaved changes autosaved {relativeTime(notice.at)}. They are not a revision yet.
          </span>
          <span className="page-actions">
            <button
              type="button"
              className="btn btn-small btn-primary"
              onClick={() => doSave(base.revision_no)}
            >
              Save as revision
            </button>
            <button
              type="button"
              className="btn btn-small"
              onClick={() =>
                discardDraft.mutate(undefined, {
                  onSuccess: () => {
                    setText(base.source_md);
                    setPersisted(base.source_md);
                    setDraftAt(null);
                    setNotice(null);
                    announce("Discarded the autosaved changes");
                  },
                })
              }
            >
              Discard changes
            </button>
          </span>
        </div>
      ) : null}
      {notice?.kind === "stale" ? (
        <div className="banner" role="status">
          <span>
            An autosaved draft from {relativeTime(notice.at)} was based on revision {notice.baseNo}, but the
            chapter is now at revision {base.revision_no}. The editor shows the saved revision.
          </span>
          <span className="page-actions">
            <button
              type="button"
              className="btn btn-small"
              onClick={() => {
                if (initial.draft) setText(initial.draft.source_md);
                setNotice(null);
              }}
            >
              Open the draft text
            </button>
            <button
              type="button"
              className="btn btn-small"
              onClick={() => discardDraft.mutate(undefined, { onSuccess: () => setNotice(null) })}
            >
              Discard draft
            </button>
          </span>
        </div>
      ) : null}
      {pendingCount > 0 && !aiOpen ? (
        <div className="banner" role="status">
          <span>
            {pendingCount === 1 ? "An AI suggestion is" : `${pendingCount} AI suggestions are`} waiting for
            your review. Nothing has been changed in the chapter.
          </span>
          <button type="button" className="btn btn-small" onClick={() => setAiOpenStored(true)}>
            Review
          </button>
        </div>
      ) : null}
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
      {saveError ? (
        <InlineError error={saveError}>
          <button type="button" className="btn btn-small" onClick={() => doSave(base.revision_no)}>
            Try saving again
          </button>
        </InlineError>
      ) : null}

      <div className="editor-toolbar" role="toolbar" aria-label="Editor options">
        <fieldset className="segmented compact">
          <legend className="visually-hidden">View</legend>
          {(
            [
              ["write", "Write"],
              ["split", "Write and preview"],
              ["preview", "Preview"],
            ] as const
          ).map(([value, label]) => (
            <label key={value}>
              <input
                type="radio"
                name={`${id}-view`}
                value={value}
                checked={view === value}
                onChange={() => setViewStored(value)}
              />
              {label}
            </label>
          ))}
        </fieldset>
        <button type="button" className="btn btn-small" disabled={locked} onClick={() => setImageOpen(true)}>
          Insert image
        </button>
        <label className="inline-check">
          <input type="checkbox" checked={plain} onChange={(e) => setPlainStored(e.target.checked)} />
          Plain text editor
        </label>
      </div>

      <div className={`panes panes-${view}`}>
        {view !== "preview" ? (
          <div className="pane">
            <SourceEditor
              ref={editor}
              value={text}
              onChange={setText}
              onSave={() => doSave(base.revision_no)}
              readOnly={locked}
              plain={plain}
              label="Chapter text (Markdown)"
              describedBy={`${id}-hint`}
            />
          </div>
        ) : null}
        {previewVisible ? (
          <div className="pane preview-pane">
            {rendered ? (
              <SanitizedHtml html={rendered.html} className="prose book-preview" label="Preview" />
            ) : preview.isError ? (
              <InlineError error={preview.error} />
            ) : (
              <Loading label="Rendering preview" />
            )}
          </div>
        ) : null}
      </div>
      {rendered && rendered.warnings.length > 0 ? (
        <section className="notes" aria-labelledby={`${id}-notes`}>
          <h2 id={`${id}-notes`}>Formatting notes</h2>
          <ul>
            {rendered.warnings.map((w, i) => (
              <li key={i}>
                {w.line ? `Line ${w.line}: ` : ""}
                {w.message}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <p className="hint" id={`${id}-hint`}>
        {wordCount !== null ? `${words(wordCount)}. ` : ""}Write in Markdown; the text is stored exactly as
        typed. Changes are autosaved as a draft; Save (Ctrl+S, or Cmd+S on a Mac) keeps a new revision.
        Tables, math ($…$), citations ([@key]), footnotes ([^1]) and images are supported.
      </p>

      <div id={`${id}-ai`} hidden={!aiOpen}>
        {aiOpen ? (
          <AiAssistPanel
            projectId={projectId}
            chapterId={chapterId}
            headNo={base.revision_no}
            dirty={dirty}
            locked={locked || aiLocked}
            onSave={() => doSave(base.revision_no)}
            getSelection={() => editor.current?.getSelection() ?? null}
            proposals={proposals.data ?? []}
          />
        ) : null}
      </div>

      <Dialog
        isOpen={historyOpen}
        onClose={() => setHistoryOpen(false)}
        title={`History of “${chapterTitle}”`}
        wide
      >
        <HistoryPanel
          projectId={projectId}
          chapterId={chapterId}
          headNo={base.revision_no}
          readOnly={locked}
          hasUnsavedText={dirty}
        />
        <div className="modal-actions">
          <button type="button" className="btn" onClick={() => setHistoryOpen(false)}>
            Close
          </button>
        </div>
      </Dialog>

      <InsertImageDialog
        isOpen={imageOpen}
        projectId={projectId}
        onClose={() => setImageOpen(false)}
        onInsert={(snippet) => {
          setImageOpen(false);
          if (view === "preview") setViewStored("split");
          setTimeout(() => editor.current?.insertBlock(snippet), 0);
          announce("Image inserted");
        }}
      />

      <Dialog
        isOpen={conflict !== null}
        onClose={() => setConflict(null)}
        title="This chapter changed somewhere else"
        role="alertdialog"
      >
        <p>
          Revision {conflict?.revision_no} was saved after you opened this chapter, probably in another
          window. Choose which text to keep. Both stay in the revision history either way.
        </p>
        <div className="modal-actions">
          <button
            type="button"
            className="btn"
            onClick={() => {
              if (conflict) {
                setBase(conflict);
                setText(conflict.source_md);
                setPersisted(conflict.source_md);
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

      <Dialog
        isOpen={blocker.state === "blocked"}
        onClose={() => blocker.reset?.()}
        title="Leave before the autosave finishes?"
        role="alertdialog"
      >
        <p>Your latest typing has not been autosaved yet.</p>
        <div className="modal-actions">
          <button type="button" className="btn" onClick={() => blocker.reset?.()}>
            Stay on this chapter
          </button>
          <button
            type="button"
            className="btn"
            onClick={() =>
              saveDraft.mutate(
                { source_md: text, base_revision_no: base.revision_no },
                { onSuccess: () => blocker.proceed?.(), onError: () => blocker.reset?.() },
              )
            }
          >
            Keep as draft and leave
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => doSave(base.revision_no, () => blocker.proceed?.())}
          >
            Save revision and leave
          </button>
        </div>
      </Dialog>
    </div>
  );
}

function InsertImageDialog({
  isOpen,
  projectId,
  onClose,
  onInsert,
}: {
  isOpen: boolean;
  projectId: string;
  onClose: () => void;
  onInsert: (snippet: string) => void;
}) {
  const id = useId();
  const uploadAsset = useUploadAsset(projectId);
  const [file, setFile] = useState<File | null>(null);
  const [caption, setCaption] = useState("");
  const [alt, setAlt] = useState("");
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setFile(null);
    setCaption("");
    setAlt("");
    setError(null);
    uploadAsset.reset();
  }

  return (
    <Dialog
      isOpen={isOpen}
      onClose={() => {
        reset();
        onClose();
      }}
      title="Insert an image"
    >
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          if (!file) return setError("Choose an image file.");
          if (!alt.trim()) return setError("Describe the image for readers who cannot see it (alt text).");
          setError(null);
          uploadAsset.mutate(file, {
            onSuccess: (asset) => {
              const esc = (s: string) =>
                s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/[{}]/g, "");
              const cap = caption.trim().replace(/([\\[\]*_`$<>~|])/g, "\\$1");
              onInsert(`![${cap}](${asset.reference}){alt="${esc(alt.trim())}"}`);
              reset();
            },
          });
        }}
      >
        {error ? (
          <p className="error" role="alert">
            {error}
          </p>
        ) : null}
        {uploadAsset.isError ? <InlineError error={uploadAsset.error} /> : null}
        <div className="field">
          <label htmlFor={`${id}-file`}>Image file</label>
          <input
            id={`${id}-file`}
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <span className="hint">
            PNG, JPEG, GIF or WebP, up to 25 MB. The file is copied into this book.
          </span>
        </div>
        <div className="field">
          <label htmlFor={`${id}-cap`}>Caption (shown under the image)</label>
          <input id={`${id}-cap`} type="text" value={caption} onChange={(e) => setCaption(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor={`${id}-alt`}>Alt text (read aloud instead of the image)</label>
          <input id={`${id}-alt`} type="text" value={alt} onChange={(e) => setAlt(e.target.value)} />
        </div>
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={uploadAsset.isPending}>
            {uploadAsset.isPending ? "Uploading…" : "Insert image"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
