import { useId, useState } from "react";
import type { RevisionMeta } from "../../api/manuscript";
import { useCompare, useRestoreRevision, useRevisions, useTagRevision } from "../../api/manuscript";
import { useAnnounce } from "../../components/Announcer";
import { ConfirmDialog } from "../../components/Dialog";
import { ErrorState, InlineError, Loading } from "../../components/States";
import { absoluteTime, relativeTime, words } from "../../lib/format";

const ORIGIN: Record<RevisionMeta["origin"], string> = {
  human: "Saved by you",
  ai_generated: "AI-generated (accepted)",
  ai_assisted: "AI-assisted (accepted)",
  imported: "Imported",
  restored: "Restored",
  system_migration: "System migration",
};

interface Props {
  projectId: string;
  chapterId: string;
  headNo: number;
  readOnly: boolean;
  hasUnsavedText: boolean;
}

/** Every saved version of a chapter, side-by-side comparison, labels and restore-as-new. */
export function HistoryPanel({ projectId, chapterId, headNo, readOnly, hasUnsavedText }: Props) {
  const revisions = useRevisions(projectId, chapterId);
  const restore = useRestoreRevision(projectId, chapterId);
  const tag = useTagRevision(projectId, chapterId);
  const announce = useAnnounce();
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const [confirm, setConfirm] = useState<RevisionMeta | null>(null);
  const [labelling, setLabelling] = useState<RevisionMeta | null>(null);
  const compare = useCompare(projectId, chapterId, from, to);
  const id = useId();

  if (revisions.isPending) return <Loading label="Loading history" />;
  if (revisions.isError)
    return <ErrorState error={revisions.error} onRetry={() => void revisions.refetch()} />;
  const list = revisions.data;
  if (list.length === 0)
    return <p className="muted">Nothing has been saved yet. Each save becomes a version here.</p>;

  return (
    <div className="history">
      <p className="muted">
        Every save is kept. Restoring copies an older version into a new revision, so nothing newer is lost.
      </p>
      <table className="plain revision-table">
        <caption className="visually-hidden">Saved versions, newest first</caption>
        <thead>
          <tr>
            <th scope="col">Version</th>
            <th scope="col">Label and note</th>
            <th scope="col">Compare</th>
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          {list.map((r) => (
            <tr key={r.id} aria-current={r.is_head ? "true" : undefined}>
              <td>
                <strong>Revision {r.revision_no}</strong>
                {r.is_head ? <span className="tag tag-gilt">Current</span> : null}
                <span className="muted block">
                  {ORIGIN[r.origin]}
                  {r.restored_from_revision_no ? ` from revision ${r.restored_from_revision_no}` : ""},{" "}
                  {words(r.word_count)}
                </span>
                <time className="muted block" dateTime={r.created_at} title={absoluteTime(r.created_at)}>
                  {relativeTime(r.created_at)}
                </time>
              </td>
              <td>
                {r.label ? (
                  <strong className="block">{r.label}</strong>
                ) : (
                  <span className="muted">No label</span>
                )}
                {r.note ? <span className="block">{r.note}</span> : null}
              </td>
              <td>
                <label className="inline-check">
                  <input
                    type="radio"
                    name={`${id}-from`}
                    checked={from === r.revision_no}
                    onChange={() => setFrom(r.revision_no)}
                  />
                  Older
                </label>
                <label className="inline-check">
                  <input
                    type="radio"
                    name={`${id}-to`}
                    checked={to === r.revision_no}
                    onChange={() => setTo(r.revision_no)}
                  />
                  Newer
                </label>
              </td>
              <td className="row-actions">
                <button type="button" className="btn btn-small" onClick={() => setLabelling(r)}>
                  Label
                </button>
                {!r.is_head ? (
                  <button
                    type="button"
                    className="btn btn-small"
                    disabled={readOnly || restore.isPending}
                    onClick={() => setConfirm(r)}
                  >
                    Restore
                  </button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {restore.isError ? <InlineError error={restore.error} /> : null}

      <section aria-labelledby={`${id}-cmp`} className="stack" style={{ marginTop: "var(--space-5)" }}>
        <h3 id={`${id}-cmp`}>Compare</h3>
        {from === null || to === null ? (
          <p className="muted">Choose an older and a newer version above to see what changed.</p>
        ) : from === to ? (
          <p className="muted">Choose two different versions.</p>
        ) : compare.isPending ? (
          <Loading label="Comparing" />
        ) : compare.isError ? (
          <ErrorState error={compare.error} />
        ) : (
          <>
            <p role="status">
              Revision {compare.data.from_revision_no} compared with revision {compare.data.to_revision_no}:{" "}
              {compare.data.changed_lines} changed, {compare.data.added_lines} added,{" "}
              {compare.data.removed_lines} removed line(s).
            </p>
            <div
              className="diff-scroll"
              tabIndex={0}
              role="region"
              aria-label="Differences between the two revisions"
            >
              <table className="diff">
                <thead>
                  <tr>
                    <th scope="col" colSpan={2}>
                      Revision {compare.data.from_revision_no}
                    </th>
                    <th scope="col" colSpan={2}>
                      Revision {compare.data.to_revision_no}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {compare.data.rows.map((row, i) => (
                    <tr key={i} className={`diff-${row.kind}`}>
                      <td className="ln">{row.left_no ?? ""}</td>
                      <td className="side">
                        {row.left.map((s, j) =>
                          !s.text ? null : s.changed ? (
                            <del key={j}>{s.text}</del>
                          ) : (
                            <span key={j}>{s.text}</span>
                          ),
                        )}
                      </td>
                      <td className="ln">{row.right_no ?? ""}</td>
                      <td className="side">
                        {row.right.map((s, j) =>
                          !s.text ? null : s.changed ? (
                            <ins key={j}>{s.text}</ins>
                          ) : (
                            <span key={j}>{s.text}</span>
                          ),
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      <ConfirmDialog
        isOpen={confirm !== null}
        title={`Restore revision ${confirm?.revision_no ?? ""}?`}
        body={
          hasUnsavedText
            ? "Its text becomes a new revision. Your unsaved changes in the editor will be replaced; save them first if you want to keep them. Every existing revision stays in history."
            : "Its text becomes a new revision. Every existing revision stays in history."
        }
        confirmLabel="Restore as new revision"
        busy={restore.isPending}
        onCancel={() => setConfirm(null)}
        onConfirm={() =>
          confirm &&
          restore.mutate(
            { revisionNo: confirm.revision_no, expectedHeadNo: headNo },
            {
              onSuccess: (res) => {
                announce(`Restored revision ${confirm.revision_no} as revision ${res.content.revision_no}`);
                setConfirm(null);
              },
              onError: () => setConfirm(null),
            },
          )
        }
      />
      <LabelDialog
        revision={labelling}
        busy={tag.isPending}
        onClose={() => setLabelling(null)}
        onSave={(label, note) =>
          labelling &&
          tag.mutate(
            { revisionNo: labelling.revision_no, label: label || null, note: note || null },
            {
              onSuccess: () => {
                announce(`Labelled revision ${labelling.revision_no}`);
                setLabelling(null);
              },
            },
          )
        }
      />
    </div>
  );
}

function LabelDialog({
  revision,
  busy,
  onClose,
  onSave,
}: {
  revision: RevisionMeta | null;
  busy: boolean;
  onClose: () => void;
  onSave: (label: string, note: string) => void;
}) {
  const id = useId();
  const [label, setLabel] = useState("");
  const [note, setNote] = useState("");
  const [current, setCurrent] = useState<string | null>(null);
  if (revision && revision.id !== current) {
    setCurrent(revision.id);
    setLabel(revision.label ?? "");
    setNote(revision.note ?? "");
  }
  if (!revision) return null;
  return (
    <div className="inline-dialog" role="group" aria-labelledby={`${id}-t`}>
      <h4 id={`${id}-t`}>Label revision {revision.revision_no}</h4>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          onSave(label.trim(), note.trim());
        }}
      >
        <div className="field">
          <label htmlFor={`${id}-label`}>Label</label>
          <input
            id={`${id}-label`}
            type="text"
            maxLength={120}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor={`${id}-note`}>Note</label>
          <textarea
            id={`${id}-note`}
            rows={3}
            maxLength={2000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
        <div className="page-actions">
          <button type="submit" className="btn btn-primary" disabled={busy}>
            Save label
          </button>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
