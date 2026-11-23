import { Link } from "react-router";
import type { Activity } from "../../api/client";
import { absoluteTime, relativeTime } from "../../lib/format";

export function ActivityList({ items, showProject = true }: { items: Activity[]; showProject?: boolean }) {
  return (
    <ol className="activity">
      {items.map((a) => (
        <li key={a.id}>
          <span>{a.summary}</span>
          {showProject && a.project_id && a.project_title ? (
            <Link className="project" to={`/projects/${a.project_id}`}>
              {a.project_title}
            </Link>
          ) : null}
          <time dateTime={a.created_at} title={absoluteTime(a.created_at)}>
            {relativeTime(a.created_at)}
          </time>
        </li>
      ))}
    </ol>
  );
}
