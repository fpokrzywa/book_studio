import { useId, useState } from "react";
import {
  useCreateLibrary,
  useImportToLibrary,
  useLibrarySources,
  useSharedLibraries,
  type Library,
} from "../../api/knowledge";
import { useAnnounce } from "../../components/Announcer";
import { PageHeader } from "../../components/Misc";
import { EmptyState, ErrorState, InlineError, Loading } from "../../components/States";
import { ImportSourceForm, SearchPanel, SourceList } from "./parts";

/** Shared libraries: sources several books can opt in to. Each book's own sources live on its Sources page. */
export function KnowledgePage() {
  const id = useId();
  const libs = useSharedLibraries();
  const create = useCreateLibrary();
  const announce = useAnnounce();
  const [name, setName] = useState("");
  if (libs.isError) return <ErrorState error={libs.error} onRetry={() => void libs.refetch()} />;
  if (!libs.data) return <Loading label="Loading libraries" />;
  return (
    <>
      <PageHeader
        title="Knowledge"
        intro="Shared libraries of reference material. Books use a shared library only when you turn it on for that book (open the book, then Sources). Each book can also keep sources of its own."
      />
      <form
        className="form panel"
        aria-labelledby={`${id}-new`}
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(
            { name: name.trim() },
            {
              onSuccess: (lib) => {
                setName("");
                announce(`Created “${lib.name}”`);
              },
            },
          );
        }}
      >
        <h2 id={`${id}-new`}>New shared library</h2>
        <div className="form-row">
          <div className="field">
            <label htmlFor={`${id}-name`}>Name</label>
            <input id={`${id}-name`} value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
          </div>
        </div>
        {create.error ? <InlineError error={create.error} /> : null}
        <div className="page-actions">
          <button type="submit" className="btn btn-primary" disabled={!name.trim() || create.isPending}>
            Create library
          </button>
        </div>
      </form>
      {libs.data.length === 0 ? (
        <EmptyState title="No shared libraries yet">
          Create one for material you use across books, such as a style manual or a reference handbook.
        </EmptyState>
      ) : (
        <div className="stack" style={{ marginTop: "var(--space-5)" }}>
          {libs.data.map((lib) => (
            <LibraryPanel key={lib.id} lib={lib} />
          ))}
        </div>
      )}
    </>
  );
}

function LibraryPanel({ lib }: { lib: Library }) {
  const id = useId();
  const sources = useLibrarySources(lib.id);
  const importer = useImportToLibrary(lib.id);
  return (
    <section className="panel" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>{lib.name}</h2>
      <p className="hint">Used by {lib.linked_project_ids.length} book(s).</p>
      {sources.data ? <SourceList sources={sources.data} /> : <Loading label="Loading sources" />}
      <div className="two-col">
        <ImportSourceForm
          label="Add a source to this library"
          pending={importer.isPending}
          error={importer.error}
          onImport={(file, allowDuplicate) => importer.mutateAsync({ file, allowDuplicate })}
        />
        <SearchPanel scope={{ libraryId: lib.id }} label="Search this library" />
      </div>
    </section>
  );
}
