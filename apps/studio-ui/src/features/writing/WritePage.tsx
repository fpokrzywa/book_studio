import { useId, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { newRequestId } from "../../api/ai";
import { useChapters, useProject } from "../../api/hooks";
import {
  FACT_KINDS,
  FINDING_STATES,
  PLAN_STATUS,
  SECTION_STATE,
  useFactActions,
  useFacts,
  useFindings,
  useOriginality,
  usePlanActions,
  usePlanHistory,
  usePlans,
  usePutSummary,
  useQualityActions,
  useSetWritingSettings,
  useSummaries,
  useWritingSettings,
  type DraftPlan,
  type DraftSection,
  type Fact,
  type QualityFinding,
  type Summary,
} from "../../api/writing";
import { useAnnounce } from "../../components/Announcer";
import { PageHeader } from "../../components/Misc";
import { InlineError, Loading } from "../../components/States";
import { relativeTime } from "../../lib/format";
import { ModelSelect } from "../planning/PlanPage";

const TABS = [
  ["drafts", "Drafts"],
  ["bible", "Story bible and summaries"],
  ["quality", "Quality checks"],
  ["originality", "Originality"],
] as const;
type Tab = (typeof TABS)[number][0];

/** Follow section-by-section drafts, keep continuity notes, and review quality findings. */
export function WritePage() {
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find(([t]) => t === params.get("tab"))?.[0] ?? "drafts") as Tab;
  const project = useProject(projectId);
  if (!project.data) return <Loading label="Loading" />;
  const readOnly = project.data.status === "archived";
  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to={`/projects/${projectId}`}>{project.data.title}</Link>
      </nav>
      <PageHeader
        title="Write and review"
        intro="AI drafts each chapter one outline section at a time and offers the whole chapter as one suggestion. Nothing reaches your manuscript until you accept it."
      />
      <nav className="plan-tabs" aria-label="Writing tools">
        <ol>
          {TABS.map(([t, label]) => (
            <li key={t}>
              <Link
                to={`?tab=${t}`}
                aria-current={t === tab ? "page" : undefined}
                onClick={() => setParams({ tab: t })}
              >
                {label}
              </Link>
            </li>
          ))}
        </ol>
      </nav>
      {tab === "drafts" ? <DraftsTab projectId={projectId} readOnly={readOnly} /> : null}
      {tab === "bible" ? <BibleTab projectId={projectId} readOnly={readOnly} /> : null}
      {tab === "quality" ? <QualityTab projectId={projectId} readOnly={readOnly} /> : null}
      {tab === "originality" ? <OriginalityTab projectId={projectId} /> : null}
    </>
  );
}

// ---------- drafts ----------

function DraftsTab({ projectId, readOnly }: { projectId: string; readOnly: boolean }) {
  const plans = usePlans(projectId);
  if (plans.isPending) return <Loading label="Loading drafts" />;
  if ((plans.data ?? []).length === 0)
    return (
      <p className="muted">
        No drafts yet. Start one from{" "}
        <Link to={`/projects/${projectId}/plan?tab=draft`}>Plan → Draft chapters</Link>.
      </p>
    );
  return (
    <ul className="plans">
      {plans.data!.map((p) => (
        <li key={p.id}>
          <PlanCard projectId={projectId} plan={p} readOnly={readOnly} />
        </li>
      ))}
    </ul>
  );
}

function PlanCard({ projectId, plan, readOnly }: { projectId: string; plan: DraftPlan; readOnly: boolean }) {
  const id = useId();
  const announce = useAnnounce();
  const actions = usePlanActions(projectId);
  const [historyOpen, setHistoryOpen] = useState(false);
  const busy = actions.pause.isPending || actions.resume.isPending || actions.cancel.isPending;
  const error = actions.pause.error ?? actions.resume.error ?? actions.cancel.error ?? actions.retry.error;
  const open = !["ready", "cancelled"].includes(plan.status);
  return (
    <article className="plan-card" aria-labelledby={`${id}-h`} data-status={plan.status}>
      <header>
        <h2 id={`${id}-h`}>{plan.chapter_title}</h2>
        <p className="plan-status">
          <strong>{PLAN_STATUS[plan.status]}</strong> · {plan.model_name} ({plan.provider_label}) · budget{" "}
          {plan.token_budget.toLocaleString()} tokens per section · started {relativeTime(plan.created_at)}
        </p>
        <p>{plan.next_step}</p>
        {plan.note ? <p className="muted">{plan.note}</p> : null}
      </header>
      {!readOnly && open ? (
        <div className="page-actions">
          {plan.status === "paused" ? (
            <button
              type="button"
              className="btn btn-small btn-primary"
              disabled={busy}
              onClick={() =>
                actions.resume.mutate(plan.id, { onSuccess: () => announce(`Resumed ${plan.chapter_title}`) })
              }
            >
              Resume
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-small"
              disabled={busy}
              onClick={() =>
                actions.pause.mutate(plan.id, { onSuccess: () => announce(`Paused ${plan.chapter_title}`) })
              }
            >
              Pause
            </button>
          )}
          <button
            type="button"
            className="btn btn-small"
            disabled={busy}
            onClick={() =>
              actions.cancel.mutate(plan.id, { onSuccess: () => announce(`Cancelled ${plan.chapter_title}`) })
            }
          >
            Cancel draft
          </button>
        </div>
      ) : null}
      {plan.status === "ready" ? (
        <p>
          <Link to={`/projects/${projectId}/chapters/${plan.chapter_id}`}>
            Review the chapter draft ({plan.proposal_status ?? "suggestion"})
          </Link>
        </p>
      ) : null}
      {error ? <InlineError error={error} /> : null}
      <ol className="sections">
        {plan.sections.map((sec) => (
          <li key={sec.id} data-state={sec.state}>
            <SectionRow projectId={projectId} plan={plan} sec={sec} readOnly={readOnly} />
          </li>
        ))}
      </ol>
      <details onToggle={(e) => setHistoryOpen((e.target as HTMLDetailsElement).open)}>
        <summary>Job history for this draft</summary>
        {historyOpen ? <History projectId={projectId} planId={plan.id} /> : null}
      </details>
    </article>
  );
}

function SectionRow({
  projectId,
  plan,
  sec,
  readOnly,
}: {
  projectId: string;
  plan: DraftPlan;
  sec: DraftSection;
  readOnly: boolean;
}) {
  const id = useId();
  const actions = usePlanActions(projectId);
  const reviewing = plan.status === "awaiting_review" && sec.state === "done" && !sec.reviewed;
  const parts = (sec.context.parts ?? []) as { key: string; label: string; tokens: number; status: string }[];
  return (
    <div className="section-row">
      <p>
        <strong>
          {sec.ordinal}. {sec.title}
        </strong>{" "}
        <span className="badge">{SECTION_STATE[sec.state]}</span>
        {sec.attempts > 1 ? <span className="muted"> · {sec.attempts} attempts</span> : null}
        {sec.edited ? <span className="muted"> · edited by you</span> : null}
      </p>
      {sec.error ? <p className="job-error">{sec.error}</p> : null}
      {!readOnly &&
      ["failed", "cancelled"].includes(sec.state) &&
      !["ready", "cancelled"].includes(plan.status) ? (
        <button
          type="button"
          className="btn btn-small"
          onClick={() => actions.retry.mutate({ planId: plan.id, sectionId: sec.id })}
        >
          Retry this section
        </button>
      ) : null}
      {reviewing && !readOnly ? (
        // Keyed by the text, so the box starts from the finished section even if it mounted earlier.
        <SectionReview key={sec.output_md ?? ""} projectId={projectId} planId={plan.id} sec={sec} />
      ) : sec.state === "done" ? (
        <details>
          <summary>Text, summary and context</summary>
          <div className="section-text">{sec.output_md}</div>
          {sec.summary ? <p className="muted">Summary: {sec.summary}</p> : null}
          <ContextTable id={`${id}-ctx`} parts={parts} sec={sec} />
        </details>
      ) : null}
    </div>
  );
}

function SectionReview({ projectId, planId, sec }: { projectId: string; planId: string; sec: DraftSection }) {
  const id = useId();
  const actions = usePlanActions(projectId);
  const [text, setText] = useState(sec.output_md ?? "");
  return (
    <div className="field">
      <label htmlFor={`${id}-text`}>Section text (edit before approving if you like)</label>
      <textarea id={`${id}-text`} rows={8} value={text} onChange={(e) => setText(e.target.value)} />
      <div className="page-actions">
        <button
          type="button"
          className="btn btn-small btn-primary"
          disabled={actions.approve.isPending}
          onClick={() =>
            actions.approve.mutate({
              planId,
              sectionId: sec.id,
              ...(text !== sec.output_md ? { edited: text } : {}),
            })
          }
        >
          Approve section and continue
        </button>
      </div>
      {actions.approve.error ? <InlineError error={actions.approve.error} /> : null}
    </div>
  );
}

function ContextTable({
  id,
  parts,
  sec,
}: {
  id: string;
  parts: { key: string; label: string; tokens: number; status: string }[];
  sec: DraftSection;
}) {
  if (!parts.length) return null;
  const used = Number(sec.context.used_tokens ?? 0);
  const budget = Number(sec.context.budget_tokens ?? 0);
  return (
    <table className="data-table" aria-describedby={id}>
      <caption id={id}>
        What the prompt included: about {used.toLocaleString()} of {budget.toLocaleString()} tokens (estimate)
      </caption>
      <thead>
        <tr>
          <th scope="col">Part</th>
          <th scope="col">Tokens</th>
          <th scope="col">Sent</th>
        </tr>
      </thead>
      <tbody>
        {parts.map((p) => (
          <tr key={p.key}>
            <th scope="row">{p.label}</th>
            <td>{p.tokens.toLocaleString()}</td>
            <td>{p.status}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function History({ projectId, planId }: { projectId: string; planId: string }) {
  const history = usePlanHistory(projectId, planId, true);
  if (history.isPending) return <Loading label="Loading history" />;
  return (
    <ol className="history">
      {(history.data ?? []).map((h) => (
        <li key={h.job_id}>
          <p>
            <strong>{h.section}</strong>, attempt {h.attempt_no}: {h.status} · {h.task} · {h.provider_kind} /{" "}
            {h.model_name} · template {h.template}
            {h.output_tokens ? ` · ${h.input_tokens ?? "?"} in / ${h.output_tokens} out tokens` : ""}
            {h.cost ? ` · ${h.cost} ${h.currency ?? ""}` : ""}
          </p>
          {h.error_message ? <p className="job-error">{h.error_message}</p> : null}
          <ul className="log">
            {h.logs.map((l, i) => (
              <li key={i}>{l.message}</li>
            ))}
          </ul>
        </li>
      ))}
    </ol>
  );
}

// ---------- story bible and summaries ----------

function BibleTab({ projectId, readOnly }: { projectId: string; readOnly: boolean }) {
  const id = useId();
  const facts = useFacts(projectId);
  const summaries = useSummaries(projectId);
  const actions = useFactActions(projectId);
  const chapters = useChapters(projectId);
  const [kind, setKind] = useState<Fact["kind"]>("character");
  const [name, setName] = useState("");
  const [attribute, setAttribute] = useState("");
  const [value, setValue] = useState("");
  const [when, setWhen] = useState("");
  return (
    <div className="stack">
      <section className="panel" aria-labelledby={`${id}-facts`}>
        <h2 id={`${id}-facts`}>Continuity notes</h2>
        <p className="hint">
          Each drafted section proposes notes about characters, places, relationships, events and open threads
          (fiction) or key terms (nonfiction). Later sections receive them. Notes from AI stay “proposed”
          until you confirm them; rejected notes are never sent again.
        </p>
        {(facts.data ?? []).length === 0 ? (
          <p className="muted">No notes yet.</p>
        ) : (
          <ul className="facts">
            {facts.data!.map((f) => (
              <li key={f.id} data-status={f.status}>
                <p>
                  <span className="badge">{FACT_KINDS.find((k) => k.value === f.kind)?.label}</span>{" "}
                  <strong>{f.name}</strong>
                  {f.attribute ? ` · ${f.attribute}` : ""}: {f.value}
                  {f.story_time ? ` (story time: ${f.story_time})` : ""}
                </p>
                <p className="muted">
                  {f.status === "proposed" ? "Proposed by AI" : f.status}
                  {f.chapter_title ? ` · ${f.chapter_title}` : ""}
                </p>
                {!readOnly ? (
                  <div className="page-actions">
                    {f.status !== "confirmed" ? (
                      <button
                        type="button"
                        className="btn btn-small"
                        onClick={() => actions.patch.mutate({ id: f.id, body: { status: "confirmed" } })}
                      >
                        Confirm<span className="visually-hidden"> {f.name}</span>
                      </button>
                    ) : null}
                    {f.status !== "rejected" ? (
                      <button
                        type="button"
                        className="btn btn-small"
                        onClick={() => actions.patch.mutate({ id: f.id, body: { status: "rejected" } })}
                      >
                        Reject<span className="visually-hidden"> {f.name}</span>
                      </button>
                    ) : null}
                    {f.kind === "thread" && f.status !== "resolved" ? (
                      <button
                        type="button"
                        className="btn btn-small"
                        onClick={() => actions.patch.mutate({ id: f.id, body: { status: "resolved" } })}
                      >
                        Mark resolved<span className="visually-hidden"> {f.name}</span>
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
        {!readOnly ? (
          <form
            className="fact-form"
            onSubmit={(e) => {
              e.preventDefault();
              actions.add.mutate(
                { kind, name, attribute, value, ...(when ? { story_time: when } : {}) },
                {
                  onSuccess: () => {
                    setName("");
                    setAttribute("");
                    setValue("");
                    setWhen("");
                  },
                },
              );
            }}
          >
            <h3>Add a note</h3>
            <div className="form-row">
              <div className="field">
                <label htmlFor={`${id}-kind`}>Kind</label>
                <select
                  id={`${id}-kind`}
                  value={kind}
                  onChange={(e) => setKind(e.target.value as Fact["kind"])}
                >
                  {FACT_KINDS.map((k) => (
                    <option key={k.value} value={k.value}>
                      {k.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor={`${id}-name`}>Name</label>
                <input
                  id={`${id}-name`}
                  required
                  maxLength={200}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
            </div>
            <div className="form-row">
              <div className="field">
                <label htmlFor={`${id}-attr`}>Detail (optional)</label>
                <input
                  id={`${id}-attr`}
                  maxLength={200}
                  placeholder="eye colour, home town, definition…"
                  value={attribute}
                  onChange={(e) => setAttribute(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor={`${id}-value`}>Value</label>
                <input
                  id={`${id}-value`}
                  required
                  maxLength={1000}
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                />
              </div>
            </div>
            <div className="field narrow">
              <label htmlFor={`${id}-when`}>Story time (optional)</label>
              <input
                id={`${id}-when`}
                maxLength={100}
                value={when}
                onChange={(e) => setWhen(e.target.value)}
              />
            </div>
            <button type="submit" className="btn btn-small">
              Add note
            </button>
            {actions.add.error ? <InlineError error={actions.add.error} /> : null}
          </form>
        ) : null}
      </section>
      <section className="panel" aria-labelledby={`${id}-sum`}>
        <h2 id={`${id}-sum`}>Chapter summaries</h2>
        <p className="hint">
          Later chapters get these summaries instead of the full text of earlier chapters, which keeps prompts
          small. Summaries of rejected drafts are not used.
        </p>
        <ul className="summaries">
          {(summaries.data ?? []).map((s) => (
            <li key={s.chapter_id}>
              <SummaryRow projectId={projectId} summary={s} readOnly={readOnly} />
            </li>
          ))}
        </ul>
        {chapters.data && chapters.data.length === 0 ? <p className="muted">No chapters yet.</p> : null}
      </section>
    </div>
  );
}

function SummaryRow({
  projectId,
  summary,
  readOnly,
}: {
  projectId: string;
  summary: Summary;
  readOnly: boolean;
}) {
  const id = useId();
  const put = usePutSummary(projectId);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(summary.text ?? "");
  return (
    <div>
      <p>
        <strong>{summary.chapter_title}</strong> <span className="muted">({summary.basis})</span>
      </p>
      {editing ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            put.mutate({ chapterId: summary.chapter_id, text }, { onSuccess: () => setEditing(false) });
          }}
        >
          <label htmlFor={`${id}-t`} className="visually-hidden">
            Summary of {summary.chapter_title}
          </label>
          <textarea
            id={`${id}-t`}
            rows={3}
            required
            maxLength={4000}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="page-actions">
            <button type="submit" className="btn btn-small btn-primary">
              Save summary
            </button>
            <button type="button" className="btn btn-small" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
          {put.error ? <InlineError error={put.error} /> : null}
        </form>
      ) : (
        <>
          <p>{summary.text ?? <span className="muted">No summary yet.</span>}</p>
          {!readOnly ? (
            <button type="button" className="btn btn-small" onClick={() => setEditing(true)}>
              {summary.text ? "Edit" : "Write"} summary
              <span className="visually-hidden"> of {summary.chapter_title}</span>
            </button>
          ) : null}
        </>
      )}
    </div>
  );
}

// ---------- quality ----------

function QualityTab({ projectId, readOnly }: { projectId: string; readOnly: boolean }) {
  const id = useId();
  const announce = useAnnounce();
  const chapters = useChapters(projectId);
  const findings = useFindings(projectId);
  const settings = useWritingSettings(projectId);
  const setSettings = useSetWritingSettings(projectId);
  const actions = useQualityActions(projectId);
  const [scope, setScope] = useState("");
  const [reviewChapter, setReviewChapter] = useState("");
  const [model, setModel] = useState("");
  const [showGone, setShowGone] = useState(false);
  const last = actions.run.data;
  const list = (findings.data ?? []).filter((f) => showGone || f.present);
  const groups = new Map<string, QualityFinding[]>();
  for (const f of list) groups.set(f.check_label, [...(groups.get(f.check_label) ?? []), f]);
  return (
    <div className="stack">
      <section className="panel" aria-labelledby={`${id}-run`}>
        <h2 id={`${id}-run`}>Run the checks</h2>
        <p className="hint">
          Local checks on your saved text: style hints, repeated phrases, duplicated paragraphs,
          factual-looking sentences without a citation, missing citations, differences from the outline and
          brief, broken links, missing alt text, inconsistent terms, undefined acronyms and (fiction)
          continuity. They look for patterns; they do not decide whether anything is true.
        </p>
        <div className="form-row">
          <div className="field">
            <label htmlFor={`${id}-scope`}>Check</label>
            <select id={`${id}-scope`} value={scope} onChange={(e) => setScope(e.target.value)}>
              <option value="">The whole book</option>
              {(chapters.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title}
                </option>
              ))}
            </select>
          </div>
        </div>
        {settings.data ? (
          <label className="inline-check">
            <input
              type="checkbox"
              disabled={readOnly}
              checked={settings.data.code_check_authorized}
              onChange={(e) => setSettings.mutate({ code_check_authorized: e.target.checked })}
            />
            Allow code checks for this book
          </label>
        ) : null}
        {settings.data ? <p className="hint">{settings.data.code_check_note}</p> : null}
        <div className="page-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={actions.run.isPending || readOnly}
            onClick={() =>
              actions.run.mutate(scope ? { chapter_id: scope, checks: [] } : { checks: [] }, {
                onSuccess: (r) => announce(`Checks done: ${r.new} new finding(s)`),
              })
            }
          >
            Run checks
          </button>
        </div>
        {actions.run.error ? <InlineError error={actions.run.error} /> : null}
        {last ? (
          <div role="status">
            <p>
              Ran {last.checks_run.length} check(s): {last.new} new finding(s), {last.seen} seen before.
            </p>
            {Object.entries(last.checks_skipped).length ? (
              <p className="muted">
                Skipped:{" "}
                {Object.entries(last.checks_skipped)
                  .map(([k, v]) => `${k} (${v})`)
                  .join("; ")}
              </p>
            ) : null}
            <p className="disclaimer">{last.disclaimer}</p>
          </div>
        ) : null}
      </section>
      <section className="panel" aria-labelledby={`${id}-ai`}>
        <h2 id={`${id}-ai`}>Ask AI for a review</h2>
        <p className="hint">
          A second opinion from a model: grammar, clarity, the brief's promise, uncited facts and (fiction)
          continuity. Only findings that quote your text word for word are kept. An AI review is not proof
          that anything is correct.
        </p>
        <div className="form-row">
          <div className="field">
            <label htmlFor={`${id}-rch`}>Chapter</label>
            <select id={`${id}-rch`} value={reviewChapter} onChange={(e) => setReviewChapter(e.target.value)}>
              <option value="">Choose a chapter</option>
              {(chapters.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor={`${id}-rmodel`}>Model</label>
            <ModelSelect id={`${id}-rmodel`} value={model} onChange={setModel} task="revise" />
          </div>
        </div>
        <button
          type="button"
          className="btn"
          disabled={!reviewChapter || readOnly || actions.aiReview.isPending}
          onClick={() => {
            const [provider_id, model_name] = model ? model.split("::") : [undefined, undefined];
            actions.aiReview.mutate(
              {
                chapter_id: reviewChapter,
                instruction: "",
                client_request_id: newRequestId(),
                ...(provider_id && model_name ? { provider_id, model_name } : {}),
              },
              { onSuccess: () => announce("AI review queued. Findings appear below when it finishes.") },
            );
          }}
        >
          Ask for a review
        </button>
        {actions.aiReview.data ? (
          <p role="status">
            Queued. Follow it in <Link to="/jobs">AI jobs</Link>; findings appear below when it finishes.
          </p>
        ) : null}
        {actions.aiReview.error ? <InlineError error={actions.aiReview.error} /> : null}
      </section>
      <section className="panel" aria-labelledby={`${id}-list`}>
        <h2 id={`${id}-list`}>Findings</h2>
        <label className="inline-check">
          <input type="checkbox" checked={showGone} onChange={(e) => setShowGone(e.target.checked)} />
          Show findings that are no longer found
        </label>
        {list.length === 0 ? <p className="muted">No findings. Run the checks.</p> : null}
        {[...groups.entries()].map(([label, items]) => (
          <section key={label} className="finding-group" aria-label={label}>
            <h3>
              {label} ({items.length})
            </h3>
            <ul className="quality-findings">
              {items.map((f) => (
                <li key={f.id} data-severity={f.severity} data-present={f.present}>
                  <FindingRow projectId={projectId} finding={f} readOnly={readOnly} />
                </li>
              ))}
            </ul>
          </section>
        ))}
      </section>
    </div>
  );
}

function FindingRow({
  projectId,
  finding: f,
  readOnly,
}: {
  projectId: string;
  finding: QualityFinding;
  readOnly: boolean;
}) {
  const id = useId();
  const actions = useQualityActions(projectId);
  const [note, setNote] = useState(f.note ?? "");
  return (
    <div>
      <p>
        {f.chapter_title ? <strong>{f.chapter_title}: </strong> : null}
        {f.message}
        {!f.present ? <span className="badge"> no longer found</span> : null}
        {f.origin === "ai_review" ? <span className="badge"> AI review, not proof</span> : null}
      </p>
      {f.excerpt ? <blockquote className="excerpt">{f.excerpt}</blockquote> : null}
      {!readOnly ? (
        <div className="form-row compact">
          <div className="field">
            <label htmlFor={`${id}-state`}>Your decision</label>
            <select
              id={`${id}-state`}
              value={f.state}
              onChange={(e) =>
                actions.patch.mutate({ id: f.id, body: { state: e.target.value as QualityFinding["state"] } })
              }
            >
              {FINDING_STATES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor={`${id}-note`}>Note</label>
            <input
              id={`${id}-note`}
              maxLength={2000}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>
          <button
            type="button"
            className="btn btn-small"
            disabled={note === (f.note ?? "")}
            onClick={() => actions.patch.mutate({ id: f.id, body: { state: f.state, note } })}
          >
            Save note
          </button>
        </div>
      ) : (
        <p className="muted">Decision: {f.state}</p>
      )}
    </div>
  );
}

// ---------- originality ----------

function OriginalityTab({ projectId }: { projectId: string }) {
  const id = useId();
  const [asked, setAsked] = useState(false);
  const report = useOriginality(projectId, asked);
  const r = report.data;
  return (
    <section className="panel" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>Originality report</h2>
      <p className="hint">
        Compares this book with itself, with your other books here and with this book's sources. It does not
        search the web or published works.
      </p>
      <button
        type="button"
        className="btn btn-primary"
        onClick={() => (asked ? void report.refetch() : setAsked(true))}
      >
        {asked ? "Run again" : "Run the report"}
      </button>
      {report.isFetching ? <Loading label="Comparing" /> : null}
      {report.error ? <InlineError error={report.error} /> : null}
      {r ? (
        <div className="originality" role="status">
          <p className="disclaimer">{r.statement}</p>
          <h3>What was compared</h3>
          <ul>
            {r.scope.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
          <h3>Not covered</h3>
          <ul>
            {r.not_covered.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
          <p className="muted">{r.external_provider}</p>
          <h3>Results</h3>
          <p>
            {r.chapters_checked} chapter(s) checked against {r.compared_with.workspace_books ?? 0} other
            book(s) and {r.compared_with.knowledge_sources ?? 0} source(s). {r.within_book.length} repeated
            paragraph(s) inside this book, {r.overlaps.length} overlap(s) with other text.
          </p>
          {r.overlaps.length ? (
            <table className="data-table">
              <caption className="visually-hidden">Overlaps with other text</caption>
              <thead>
                <tr>
                  <th scope="col">Where</th>
                  <th scope="col">Shares at least</th>
                  <th scope="col">With</th>
                  <th scope="col">Cited?</th>
                </tr>
              </thead>
              <tbody>
                {r.overlaps.map((o, i) => (
                  <tr key={i}>
                    <th scope="row">
                      {String(o.chapter)}, paragraph {String(o.paragraph)}
                    </th>
                    <td>{String(o.shared_words_at_least)} words in a row</td>
                    <td>
                      {o.kind === "knowledge_source" ? "Source: " : "Your book: "}
                      {String(o.matched_with)}
                    </td>
                    <td>{o.cited_in_paragraph ? "Yes" : "No"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {r.within_book.length ? (
            <ul>
              {r.within_book.map((w, i) => (
                <li key={i}>{String(w.message)}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
