import { Link } from "react-router";
import { useProjects } from "../../api/hooks";
import { PageHeader } from "../../components/Misc";
import { EmptyState, ErrorState, Loading } from "../../components/States";
import { n, relativeTime, typeLabel, words } from "../../lib/format";

export function ManuscriptsPage() {
  const projects = useProjects({ status: "active", sort: "updated_at", order: "desc" });

  return (
    <>
      <PageHeader
        title="Manuscripts"
        intro="Jump straight into writing. Books are listed by when you last worked on them."
      />
      {projects.isPending ? (
        <Loading />
      ) : projects.isError ? (
        <ErrorState error={projects.error} onRetry={() => void projects.refetch()} />
      ) : projects.data.items.length === 0 ? (
        <EmptyState
          title="No manuscripts yet"
          action={
            <Link to="/new" className="btn btn-primary">
              Start a book
            </Link>
          }
        >
          A manuscript appears here as soon as you create a book.
        </EmptyState>
      ) : (
        <div className="panel">
          <table className="plain">
            <caption className="visually-hidden">Active manuscripts</caption>
            <thead>
              <tr>
                <th scope="col">Book</th>
                <th scope="col">Kind</th>
                <th scope="col">Chapters</th>
                <th scope="col">Written</th>
                <th scope="col">Last edited</th>
              </tr>
            </thead>
            <tbody>
              {projects.data.items.map((p) => (
                <tr key={p.id}>
                  <td>
                    <Link to={`/projects/${p.id}`}>{p.title}</Link>
                  </td>
                  <td>{typeLabel(p.project_type)}</td>
                  <td>{n(p.chapter_count)}</td>
                  <td>
                    {words(p.word_count)}
                    {p.target_word_count ? ` of ${n(p.target_word_count)}` : ""}
                  </td>
                  <td>
                    <time dateTime={p.updated_at}>{relativeTime(p.updated_at)}</time>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
