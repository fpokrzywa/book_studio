import { useId, useState } from "react";
import { Link } from "react-router";
import { ACTIVE, STAGES, TASKS, useJobActions, useJobLogs, useJobs, useUsage, type Job } from "../../api/ai";
import { PageHeader } from "../../components/Misc";
import { EmptyState, ErrorState, InlineError, Loading } from "../../components/States";
import { absoluteTime, relativeTime } from "../../lib/format";

const STATUS_TEXT: Record<Job["status"], string> = {
  queued: "Queued",
  running: "Running",
  succeeded: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
  interrupted: "Interrupted",
};

/** Status center: every AI job with its stages, logs and costs. Progress is shown as stages, never invented percentages. */
export function JobsPage() {
  const jobs = useJobs({});
  const usage = useUsage();
  const actions = useJobActions();
  const [open, setOpen] = useState<string | null>(null);
  if (jobs.isError) return <ErrorState error={jobs.error} onRetry={() => void jobs.refetch()} />;
  if (!jobs.data) return <Loading label="Loading AI jobs" />;
  const actionError = actions.cancel.error ?? actions.retry.error;
  return (
    <>
      <PageHeader
        title="AI jobs"
        intro="Everything you asked an AI model to do, what happened, and what it cost. Suggestions are reviewed in the chapter."
      />
      {actionError ? <InlineError error={actionError} /> : null}
      {jobs.data.length === 0 ? (
        <EmptyState title="No AI jobs yet">
          Open a chapter and use AI assist to ask for a suggestion.
        </EmptyState>
      ) : (
        <table className="data-table jobs-table">
          <caption className="visually-hidden">AI jobs, newest first</caption>
          <thead>
            <tr>
              <th scope="col">Job</th>
              <th scope="col">Where</th>
              <th scope="col">Status</th>
              <th scope="col">Started</th>
              <th scope="col">
                <span className="visually-hidden">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {jobs.data.map((j) => (
              <JobRow
                key={j.id}
                job={j}
                open={open === j.id}
                onToggle={() => setOpen(open === j.id ? null : j.id)}
                onCancel={() => actions.cancel.mutate(j.id)}
                onRetry={() => actions.retry.mutate(j.id)}
              />
            ))}
          </tbody>
        </table>
      )}
      <CostTable usage={usage} />
    </>
  );
}

function JobRow({
  job: j,
  open,
  onToggle,
  onCancel,
  onRetry,
}: {
  job: Job;
  open: boolean;
  onToggle: () => void;
  onCancel: () => void;
  onRetry: () => void;
}) {
  const id = useId();
  const active = ACTIVE.includes(j.status);
  const stage = j.cancel_requested && active ? STAGES.cancelling : (STAGES[j.stage] ?? j.stage);
  const task = TASKS.find((t) => t.value === j.task)?.label ?? j.task;
  return (
    <>
      <tr data-status={j.status}>
        <th scope="row">
          {task} with {j.model_name}
          <div className="muted">
            {j.project_title}
            {j.chapter_title ? (
              <>
                {" · "}
                <Link to={`/projects/${j.project_id}/chapters/${j.chapter_id}`}>{j.chapter_title}</Link>
              </>
            ) : null}
          </div>
        </th>
        <td>
          {j.provider_label ?? j.provider_kind}
          <div className="muted">{j.provider_local ? "On this computer" : "Cloud"}</div>
        </td>
        <td>
          <strong>{STATUS_TEXT[j.status]}</strong>
          <div className="muted">
            {stage}
            {j.status === "running" && j.received_chars
              ? `, ${j.received_chars.toLocaleString()} characters`
              : ""}
            {j.attempt > 0 ? ` · attempt ${j.attempt} of ${j.max_attempts}` : ""}
          </div>
          {j.error_message ? <div className="job-error">{j.error_message}</div> : null}
          {j.status === "succeeded" && j.proposal_id ? (
            <Link to={`/projects/${j.project_id}/chapters/${j.chapter_id}`}>Review in the chapter</Link>
          ) : null}
        </td>
        <td>
          <time dateTime={j.created_at} title={absoluteTime(j.created_at)}>
            {relativeTime(j.created_at)}
          </time>
        </td>
        <td>
          <div className="page-actions">
            <button
              type="button"
              className="btn btn-small"
              aria-expanded={open}
              aria-controls={`${id}-log`}
              onClick={onToggle}
            >
              {open ? "Hide log" : "Log"}
            </button>
            {active && !j.cancel_requested ? (
              <button type="button" className="btn btn-small" onClick={onCancel}>
                Cancel
              </button>
            ) : null}
            {["failed", "cancelled", "interrupted"].includes(j.status) ? (
              <button type="button" className="btn btn-small" onClick={onRetry}>
                Retry
              </button>
            ) : null}
          </div>
        </td>
      </tr>
      {open ? (
        <tr id={`${id}-log`}>
          <td colSpan={5}>
            <JobLogView job={j} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

function JobLogView({ job }: { job: Job }) {
  const logs = useJobLogs(job.id, ACTIVE.includes(job.status));
  const est = job.estimate as { input_tokens?: number; max_output_tokens?: number; cost_note?: string };
  return (
    <div className="job-log">
      <p className="muted">
        Estimate before running: about {est.input_tokens?.toLocaleString() ?? "?"} tokens in, up to{" "}
        {est.max_output_tokens?.toLocaleString() ?? "?"} out. {est.cost_note}
      </p>
      {logs.data ? (
        <ol>
          {logs.data.map((l, i) => (
            <li key={i} data-level={l.level}>
              <time dateTime={l.ts}>{absoluteTime(l.ts)}</time> {l.message}
            </li>
          ))}
        </ol>
      ) : (
        <Loading label="Loading the log" />
      )}
      {job.partial_output ? (
        <details>
          <summary>Text received before it stopped</summary>
          <pre className="partial">{job.partial_output}</pre>
        </details>
      ) : null}
    </div>
  );
}

function CostTable({ usage }: { usage: ReturnType<typeof useUsage> }) {
  const id = useId();
  if (!usage.data) return null;
  const { rows, totals } = usage.data;
  return (
    <section className="panel" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>Usage and cost</h2>
      <p className="hint">
        Token counts come from the provider when it reports them. Costs use the prices you entered in AI
        settings; without a price the cost is shown as unknown, never guessed.
      </p>
      {totals.length > 0 ? (
        <ul className="totals">
          {totals.map((t) => (
            <li key={t.currency ?? "none"}>
              {t.currency ? (
                <>
                  <strong>
                    {t.amount ?? "0"} {t.currency}
                  </strong>{" "}
                  across {t.calls} calls
                </>
              ) : (
                <>
                  <strong>{t.calls} calls</strong> with no currency (local models, or no price entered)
                </>
              )}
              {t.unknown_cost_calls ? `, ${t.unknown_cost_calls} with unknown cost` : ""}
            </li>
          ))}
        </ul>
      ) : null}
      {rows.length === 0 ? (
        <p className="muted">No usage yet.</p>
      ) : (
        <table className="data-table">
          <caption className="visually-hidden">Usage per call</caption>
          <thead>
            <tr>
              <th scope="col">When</th>
              <th scope="col">Model</th>
              <th scope="col">Tokens in / out</th>
              <th scope="col">Cost</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>
                  <time dateTime={r.created_at} title={absoluteTime(r.created_at)}>
                    {relativeTime(r.created_at)}
                  </time>
                  <div className="muted">{r.project_title}</div>
                </td>
                <th scope="row">
                  {r.model_name}
                  <div className="muted">{r.provider_kind}</div>
                </th>
                <td>
                  {r.input_tokens?.toLocaleString() ?? "?"} / {r.output_tokens?.toLocaleString() ?? "?"}
                  <div className="muted">
                    {r.reported_by_provider ? "reported by the provider" : "not reported"}
                  </div>
                </td>
                <td>
                  {r.cost_amount === null
                    ? "Unknown"
                    : r.currency
                      ? `${r.cost_amount} ${r.currency}`
                      : "No charge"}
                  <div className="muted">{r.price_basis}</div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
