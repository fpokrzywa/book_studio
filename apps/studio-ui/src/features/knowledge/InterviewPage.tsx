import { useId, useState } from "react";
import { Link, useParams } from "react-router";
import { useProject } from "../../api/hooks";
import { useInterview, useInterviewActions, type Interview } from "../../api/knowledge";
import { useAnnounce } from "../../components/Announcer";
import { PageHeader } from "../../components/Misc";
import { ErrorState, InlineError, Loading } from "../../components/States";
import { absoluteTime, relativeTime } from "../../lib/format";

type Question = Interview["questions"][number];

/** Interview-to-book: the author's stories in their exact words. AI may draw on them, never invent them. */
export function InterviewPage() {
  const { projectId = "" } = useParams();
  const id = useId();
  const announce = useAnnounce();
  const project = useProject(projectId);
  const interview = useInterview(projectId);
  const actions = useInterviewActions(projectId);
  const [prompt, setPrompt] = useState("");
  if (interview.isError)
    return <ErrorState error={interview.error} onRetry={() => void interview.refetch()} />;
  if (!project.data || !interview.data) return <Loading label="Loading the interview" />;
  const archived = project.data.status === "archived";
  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to={`/projects/${projectId}`}>{project.data.title}</Link>
      </nav>
      <PageHeader
        title="Interview"
        intro={`Answer in your own words; answers are saved exactly as you type them, and changing one keeps the earlier version. When you ask AI to use your interview, it may only use what you wrote here and is told never to invent an experience. ${interview.data.answered} of ${interview.data.questions.length} answered.`}
      />
      <div className="banner" role="note">
        If an answer mentions other people, make sure you are comfortable with their story appearing in your
        book.
      </div>
      <ol className="interview">
        {interview.data.questions.map((q) => (
          <QuestionItem key={q.id} q={q} projectId={projectId} readOnly={archived} />
        ))}
      </ol>
      {!archived ? (
        <form
          className="form panel"
          aria-labelledby={`${id}-add`}
          onSubmit={(e) => {
            e.preventDefault();
            actions.addQuestion.mutate(prompt.trim(), {
              onSuccess: () => {
                setPrompt("");
                announce("Question added");
              },
            });
          }}
        >
          <h2 id={`${id}-add`}>Add your own question</h2>
          <div className="field">
            <label htmlFor={`${id}-q`}>Question</label>
            <input
              id={`${id}-q`}
              value={prompt}
              maxLength={1000}
              onChange={(e) => setPrompt(e.target.value)}
            />
          </div>
          {actions.addQuestion.error ? <InlineError error={actions.addQuestion.error} /> : null}
          <div className="page-actions">
            <button type="submit" className="btn" disabled={prompt.trim().length < 3}>
              Add question
            </button>
          </div>
        </form>
      ) : null}
    </>
  );
}

function QuestionItem({ q, projectId, readOnly }: { q: Question; projectId: string; readOnly: boolean }) {
  const id = useId();
  const announce = useAnnounce();
  const actions = useInterviewActions(projectId);
  const [text, setText] = useState(q.answer?.answer_text ?? "");
  const saved = q.answer?.answer_text ?? "";
  const dirty = text !== saved;
  return (
    <li className="question">
      <label htmlFor={`${id}-a`} className="question-prompt">
        {q.prompt}
        {q.origin === "author" ? <span className="muted"> (your question)</span> : null}
      </label>
      <textarea
        id={`${id}-a`}
        rows={5}
        value={text}
        readOnly={readOnly}
        maxLength={50_000}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="page-actions">
        <button
          type="button"
          className="btn btn-small btn-primary"
          disabled={readOnly || !dirty || actions.answer.isPending}
          onClick={() =>
            actions.answer.mutate(
              { questionId: q.id, answer_text: text },
              { onSuccess: () => announce("Answer saved, word for word") },
            )
          }
        >
          Save answer
        </button>
        <span className="muted" aria-live="off">
          {dirty
            ? "Not saved"
            : q.answer
              ? `Saved ${relativeTime(q.answer.answered_at)}`
              : "Not answered yet"}
        </span>
      </div>
      {q.history.length > 1 ? (
        <details>
          <summary>Earlier versions ({q.history.length - 1})</summary>
          <ol>
            {q.history.slice(0, -1).map((a) => (
              <li key={a.id}>
                <time dateTime={a.answered_at}>{absoluteTime(a.answered_at)}</time>
                <blockquote>{a.answer_text}</blockquote>
              </li>
            ))}
          </ol>
        </details>
      ) : null}
      {actions.answer.error ? <InlineError error={actions.answer.error} /> : null}
    </li>
  );
}
