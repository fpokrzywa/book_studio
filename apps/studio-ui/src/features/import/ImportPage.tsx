import { useId, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import type { ProjectType } from "../../api/client";
import { useProjects } from "../../api/hooks";
import type { ImportPreview } from "../../api/manuscript";
import { useCancelImport, useCommitImport, useStartImport } from "../../api/manuscript";
import { useAnnounce } from "../../components/Announcer";
import { PageHeader } from "../../components/Misc";
import { InlineError } from "../../components/States";
import { n, PROJECT_TYPES, words } from "../../lib/format";

const IMPORTER_LABEL: Record<ImportPreview["importer"], string> = {
  markdown: "Markdown",
  text: "Plain text",
  html: "HTML",
  docx: "Word (DOCX)",
  pdf: "PDF (text only)",
};

export function ImportPage() {
  const [params] = useSearchParams();
  const into = params.get("into") ?? "";
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  return (
    <>
      <PageHeader
        title="Import a manuscript"
        intro="Bring in Markdown, text, HTML, Word (.docx) or text-based PDF files. You see the detected chapters before anything is added, and the original file is kept unchanged."
      />
      {preview ? (
        <ImportReview preview={preview} defaultInto={into} onRestart={() => setPreview(null)} />
      ) : (
        <ImportUpload defaultInto={into} onPreview={setPreview} />
      )}
    </>
  );
}

function ImportUpload({
  defaultInto,
  onPreview,
}: {
  defaultInto: string;
  onPreview: (p: ImportPreview) => void;
}) {
  const id = useId();
  const start = useStartImport();
  const projects = useProjects({ status: "active", sort: "title", order: "asc" });
  const [file, setFile] = useState<File | null>(null);
  const [into, setInto] = useState(defaultInto);
  const [error, setError] = useState<string | null>(null);
  const [over, setOver] = useState(false);

  return (
    <form
      className="form"
      onSubmit={(e) => {
        e.preventDefault();
        if (!file) return setError("Choose a file to import.");
        setError(null);
        start.mutate({ file, targetProjectId: into || undefined }, { onSuccess: onPreview });
      }}
    >
      {/* Dropping a file is a shortcut; the labelled file input inside is the accessible path. */}
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions */}
      <div
        className="dropzone"
        data-over={over}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          const dropped = e.dataTransfer.files?.[0];
          if (dropped) setFile(dropped);
        }}
      >
        <label htmlFor={`${id}-file`} className="label">
          File
        </label>
        <input
          id={`${id}-file`}
          type="file"
          accept=".md,.markdown,.txt,.text,.html,.htm,.xhtml,.docx,.pdf"
          aria-describedby={`${id}-file-hint`}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <span className="hint" id={`${id}-file-hint`}>
          Or drop a file here. Up to 200 MB. Scanned PDFs need text recognition, which is not available yet.
        </span>
        {file ? <p className="muted">Selected: {file.name}</p> : null}
      </div>
      <div className="field">
        <label htmlFor={`${id}-into`}>Import into</label>
        <select id={`${id}-into`} value={into} onChange={(e) => setInto(e.target.value)}>
          <option value="">A new book</option>
          {(projects.data?.items ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.title}
            </option>
          ))}
        </select>
      </div>
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      {start.isError ? <InlineError error={start.error} /> : null}
      <div className="page-actions">
        <button type="submit" className="btn btn-primary" disabled={start.isPending}>
          {start.isPending ? "Reading the file…" : "Show what will be imported"}
        </button>
      </div>
    </form>
  );
}

function ImportReview({
  preview,
  defaultInto,
  onRestart,
}: {
  preview: ImportPreview;
  defaultInto: string;
  onRestart: () => void;
}) {
  const id = useId();
  const navigate = useNavigate();
  const announce = useAnnounce();
  const commit = useCommitImport();
  const cancel = useCancelImport();
  const into = preview.target_project_id ?? defaultInto;
  const [include, setInclude] = useState<Set<number>>(() => new Set(preview.chapters.map((c) => c.index)));
  const [title, setTitle] = useState(preview.suggested_title);
  const [kind, setKind] = useState<ProjectType>("nonfiction");

  if (preview.status === "failed") {
    return (
      <section className="state state-error" role="alert">
        <h2>“{preview.original_name}” could not be imported</h2>
        {preview.warnings.map((w) => (
          <p key={w.code + w.message}>{w.message}</p>
        ))}
        <p>
          The uploaded file was kept unchanged, in case you need it later. Nothing was added to your books.
        </p>
        <button type="button" className="btn" onClick={onRestart}>
          Choose another file
        </button>
      </section>
    );
  }

  const chosen = preview.chapters.filter((c) => include.has(c.index));
  const totalWords = chosen.reduce((s, c) => s + c.word_count, 0);

  return (
    <div className="stack">
      <section className="panel" aria-labelledby={`${id}-sum`}>
        <h2 id={`${id}-sum`}>{preview.original_name}</h2>
        <p>
          Read as {IMPORTER_LABEL[preview.importer]}:{" "}
          {preview.chapters.length === 1 ? "1 chapter" : `${preview.chapters.length} chapters`} detected.{" "}
          {preview.lossy ? (
            <strong>Some formatting could not be carried over; check the notes below.</strong>
          ) : (
            "The text is imported exactly as written."
          )}
        </p>
        {preview.warnings.length > 0 ? (
          <>
            <h3 className="subhead">Notes about this file</h3>
            <ul className="notes-list">
              {preview.warnings.map((w, i) => (
                <li key={i}>{w.message}</li>
              ))}
            </ul>
          </>
        ) : null}
      </section>

      <fieldset className="panel">
        <legend>
          <h2>Chapters to import</h2>
        </legend>
        <ol className="import-chapters">
          {preview.chapters.map((c) => (
            <li key={c.index}>
              <label className="inline-check">
                <input
                  type="checkbox"
                  checked={include.has(c.index)}
                  onChange={(e) => {
                    const next = new Set(include);
                    if (e.target.checked) next.add(c.index);
                    else next.delete(c.index);
                    setInclude(next);
                  }}
                />
                <strong>{c.title}</strong>
              </label>
              <span className="muted block">
                {words(c.word_count)}, {c.block_count} blocks
                {c.image_count ? `, ${c.image_count} image(s)` : ""}
              </span>
              {c.duplicate_reason ? (
                <span className="warn block">Possible duplicate: {c.duplicate_reason}.</span>
              ) : null}
              <details>
                <summary>Show the beginning of the text</summary>
                <pre className="source-peek" tabIndex={0}>
                  {c.preview_source || "(empty)"}
                </pre>
              </details>
            </li>
          ))}
        </ol>
      </fieldset>

      {!into ? (
        <div className="form-row">
          <div className="field">
            <label htmlFor={`${id}-title`}>New book title</label>
            <input
              id={`${id}-title`}
              type="text"
              maxLength={300}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor={`${id}-kind`}>Kind of book</label>
            <select id={`${id}-kind`} value={kind} onChange={(e) => setKind(e.target.value as ProjectType)}>
              {PROJECT_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      ) : null}

      {commit.isError ? <InlineError error={commit.error} /> : null}
      <div className="page-actions">
        <button
          type="button"
          className="btn btn-primary"
          disabled={commit.isPending || chosen.length === 0 || (!into && !title.trim())}
          onClick={() =>
            commit.mutate(
              {
                id: preview.id,
                body: into
                  ? {
                      mode: "existing_project",
                      project_id: into,
                      project_type: kind,
                      include: [...include].sort((a, b) => a - b),
                    }
                  : {
                      mode: "new_project",
                      project_title: title.trim(),
                      project_type: kind,
                      include: [...include].sort((a, b) => a - b),
                    },
              },
              {
                onSuccess: (res) => {
                  announce(`Imported ${res.chapter_ids.length} chapter(s)`);
                  navigate(`/projects/${res.project_id}`);
                },
              },
            )
          }
        >
          {commit.isPending
            ? "Importing…"
            : `Import ${chosen.length === 1 ? "1 chapter" : `${chosen.length} chapters`} (${n(totalWords)} words)`}
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => cancel.mutate(preview.id, { onSuccess: onRestart })}
          disabled={cancel.isPending}
        >
          Cancel import
        </button>
      </div>
    </div>
  );
}
