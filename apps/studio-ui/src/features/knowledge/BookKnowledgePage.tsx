import { useId } from "react";
import { Link, useParams } from "react-router";
import { useProject } from "../../api/hooks";
import { useBookKnowledge, useBookSources, useImportToBook, useLinkLibrary } from "../../api/knowledge";
import { PageHeader } from "../../components/Misc";
import { ErrorState, InlineError, Loading } from "../../components/States";
import { ImportSourceForm, SearchPanel, SourceList } from "./parts";

/** A book's sources: its own files plus shared libraries it opted into. */
export function BookKnowledgePage() {
  const { projectId = "" } = useParams();
  const id = useId();
  const project = useProject(projectId);
  const book = useBookKnowledge(projectId);
  const sources = useBookSources(projectId);
  const importer = useImportToBook(projectId);
  const link = useLinkLibrary(projectId);
  const failed = [project, book, sources].find((q) => q.isError);
  if (failed) return <ErrorState error={failed.error} onRetry={() => void book.refetch()} />;
  if (!project.data || !book.data || !sources.data) return <Loading label="Loading sources" />;
  const archived = project.data.status === "archived";
  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to={`/projects/${projectId}`}>{project.data.title}</Link>
      </nav>
      <PageHeader
        title="Sources"
        intro="Reference material for this book. AI suggestions can draw on enabled sources and cite the exact passage; nothing here is ever treated as an instruction."
        actions={
          <Link className="btn" to={`/projects/${projectId}/evidence`}>
            Evidence ledger
          </Link>
        }
      />
      <div className="two-col">
        <div className="stack">
          <section className="panel" aria-labelledby={`${id}-sources`}>
            <h2 id={`${id}-sources`}>
              {book.data.usable_source_count} source(s) available to AI for this book
            </h2>
            <SourceList sources={sources.data} readOnly={archived} />
            {!archived ? (
              <ImportSourceForm
                label="Add a source to this book"
                pending={importer.isPending}
                error={importer.error}
                onImport={(file, allowDuplicate) => importer.mutateAsync({ file, allowDuplicate })}
              />
            ) : null}
          </section>
        </div>
        <div className="stack">
          <section className="panel" aria-labelledby={`${id}-search`}>
            <h2 id={`${id}-search`}>Search this book's sources</h2>
            <SearchPanel scope={{ projectId }} label="Find a passage" />
          </section>
          <section className="panel" aria-labelledby={`${id}-shared`}>
            <h2 id={`${id}-shared`}>Shared libraries</h2>
            <p className="hint">
              Shared libraries hold sources several books can use. A book uses one only if you turn it on
              here. <Link to="/knowledge">Manage shared libraries</Link>
            </p>
            {link.error ? <InlineError error={link.error} /> : null}
            {[...book.data.linked, ...book.data.available_shared].length === 0 ? (
              <p className="muted">No shared libraries yet.</p>
            ) : (
              <ul className="checks">
                {[...book.data.linked, ...book.data.available_shared].map((lib) => {
                  const on = book.data.linked.some((l) => l.id === lib.id);
                  return (
                    <li key={lib.id}>
                      <label className="inline-check">
                        <input
                          type="checkbox"
                          checked={on}
                          disabled={archived || link.isPending}
                          onChange={(e) => link.mutate({ libraryId: lib.id, on: e.target.checked })}
                        />
                        {lib.name} <span className="muted">({lib.source_count} sources)</span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
