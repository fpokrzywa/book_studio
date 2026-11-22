import type { CSSProperties } from "react";
import { Link } from "react-router";
import type { Project } from "../../api/client";
import { languageName, n, progress, relativeTime, spineVar, typeLabel, words } from "../../lib/format";

/** A project shown as a bound volume: spine colour = kind of book, ribbon length = progress. */
export function ProjectVolume({ project }: { project: Project }) {
  const ratio = progress(project.word_count, project.target_word_count);
  const progressText =
    project.target_word_count != null
      ? `${n(project.word_count)} of ${n(project.target_word_count)} words`
      : words(project.word_count);

  return (
    <article className="volume" style={{ "--spine": spineVar(project.project_type) } as CSSProperties}>
      {ratio != null ? (
        <div className="ribbon" aria-hidden="true">
          <span style={{ height: `${Math.max(4, ratio * 100)}%` }} />
        </div>
      ) : null}
      <div>
        <h3>
          <Link to={`/projects/${project.id}`}>{project.title}</Link>
        </h3>
        {project.subtitle ? <p className="subtitle">{project.subtitle}</p> : null}
        {project.author_name ? <p className="author">{project.author_name}</p> : null}
      </div>
      <dl>
        <dt>Kind</dt>
        <dd>{typeLabel(project.project_type)}</dd>
        <dt>Language</dt>
        <dd>{languageName(project.language)}</dd>
        <dt>Written</dt>
        <dd>
          {progressText}
          {ratio != null ? ` (${Math.round(ratio * 100)}%)` : ""}
        </dd>
        <dt>Chapters</dt>
        <dd>{n(project.chapter_count)}</dd>
        {project.audience ? (
          <>
            <dt>For</dt>
            <dd>{project.audience}</dd>
          </>
        ) : null}
      </dl>
      <div className="tags">
        <span className="muted" style={{ fontSize: "var(--step--1)" }}>
          Edited <time dateTime={project.updated_at}>{relativeTime(project.updated_at)}</time>
        </span>
        {project.status === "archived" ? <span className="tag">Archived</span> : null}
        {project.is_demo ? <span className="tag tag-gilt">Demo</span> : null}
      </div>
    </article>
  );
}
