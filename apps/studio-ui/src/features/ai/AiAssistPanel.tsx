import { useEffect, useId, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import { ApiError } from "../../api/client";
import {
  ACTIVE,
  aiKeys,
  STAGES,
  TASKS,
  newRequestId,
  useConsentActions,
  useEnqueue,
  useEstimate,
  useJobActions,
  useJobs,
  useProposalActions,
  useProviders,
  useRoutes,
  whereLabel,
  type AiRequest,
  type AiTask,
  type Estimate,
  type Job,
  type Proposal,
  type ProposalMode,
} from "../../api/ai";
import { useSystemInfo } from "../../api/hooks";
import { useBookKnowledge, useProfiles } from "../../api/knowledge";
import { passageLink } from "../knowledge/parts";
import { useAnnounce } from "../../components/Announcer";
import { InlineError } from "../../components/States";
import { relativeTime } from "../../lib/format";

export interface Selection {
  start: number;
  end: number;
  text: string;
}

interface Props {
  projectId: string;
  chapterId: string;
  headNo: number;
  dirty: boolean;
  locked: boolean;
  onSave: () => void;
  getSelection: () => Selection | null;
  proposals: Proposal[];
}

const NOTE_TASKS: AiTask[] = ["summarize", "brainstorm", "outline", "research"];

function modeFor(task: AiTask, placement: "end" | "cursor", sel: Selection | null): ProposalMode {
  if (NOTE_TASKS.includes(task)) return "note";
  if (task === "revise") return "replace_selection";
  if (task === "translate") return sel && sel.end > sel.start ? "replace_selection" : "append";
  return placement === "cursor" ? "insert_at" : "append";
}

/** The AI panel beside the editor: ask, follow the job, then review suggestions. Nothing is applied without Accept. */
export function AiAssistPanel(props: Props) {
  const { projectId, chapterId, proposals } = props;
  const id = useId();
  return (
    <section className="ai-assist" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>AI assist</h2>
      <p className="muted">
        Suggestions appear here for review. Your chapter changes only when you choose Accept, and every
        accepted suggestion becomes a new revision you can undo from History.
      </p>
      <ReviewPane {...props} proposals={proposals} />
      <RequestForm {...props} />
      <ChapterJobs projectId={projectId} chapterId={chapterId} />
    </section>
  );
}

function RequestForm({ projectId, chapterId, headNo, dirty, locked, onSave, getSelection }: Props) {
  const id = useId();
  const announce = useAnnounce();
  const info = useSystemInfo();
  const providers = useProviders();
  const routes = useRoutes();
  const estimate = useEstimate(projectId);
  const enqueue = useEnqueue(projectId);
  const consent = useConsentActions(projectId);

  const [task, setTask] = useState<AiTask>("draft");
  const [instruction, setInstruction] = useState("");
  const [choice, setChoice] = useState("default");
  const [placement, setPlacement] = useState<"end" | "cursor">("end");
  const [maxTokens, setMaxTokens] = useState("");
  const [language, setLanguage] = useState("");
  const [useSources, setUseSources] = useState(true);
  const [useInterview, setUseInterview] = useState(false);
  const [voiceId, setVoiceId] = useState("");
  const knowledge = useBookKnowledge(projectId);
  const profiles = useProfiles();
  const usable = knowledge.data?.usable_source_count ?? 0;
  const [selection, setSelection] = useState<Selection | null>(null);
  const [requestId, setRequestId] = useState(newRequestId);

  const route = routes.data?.find((r) => r.task === task);
  const options = useMemo(
    () =>
      (providers.data ?? [])
        .filter((p) => p.enabled)
        .map((p) => ({ provider: p, models: p.models.map((m) => m.name) }))
        .filter((g) => g.models.length > 0),
    [providers.data],
  );
  const [providerId, model] = choice === "default" ? [undefined, undefined] : choice.split("::");
  const chosenProvider = providerId ? providers.data?.find((p) => p.id === providerId) : undefined;
  const mode = modeFor(task, placement, selection);
  const needsSelection = mode === "replace_selection";
  const hasSelection = selection !== null && selection.end > selection.start;

  const body: AiRequest = {
    chapter_id: chapterId,
    task,
    instruction,
    mode,
    base_revision_no: headNo,
    client_request_id: requestId,
    ...(providerId && model ? { provider_id: providerId, model_name: model } : {}),
    ...(maxTokens ? { max_output_tokens: Number(maxTokens) } : {}),
    ...(task === "translate" && language ? { target_language: language } : {}),
    use_sources: useSources,
    use_interview: useInterview,
    ...(task === "revise" && voiceId ? { voice_profile_id: voiceId } : {}),
    ...(selection && (needsSelection || mode === "insert_at")
      ? {
          selection_start: selection.start,
          selection_end: mode === "insert_at" ? selection.start : selection.end,
        }
      : {}),
  };
  const ready = !dirty && !locked && (choice !== "default" || route) && (!needsSelection || hasSelection);
  const key = JSON.stringify({ ...body, client_request_id: "" });

  // Estimate before running: tokens and, when a price is known, an upper bound on the charge.
  useEffect(() => {
    if (!ready) return;
    const t = setTimeout(() => estimate.mutate(body), 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ready]);

  const est = ready ? estimate.data : undefined;
  const refreshSelection = () => setSelection(getSelection());

  return (
    <form
      className="ai-form"
      aria-labelledby={`${id}-ask`}
      onFocusCapture={refreshSelection}
      onSubmit={(e) => {
        e.preventDefault();
        refreshSelection();
        if (!ready || est?.blocked_reason) return;
        enqueue.mutate(body, {
          onSuccess: (job) => {
            setRequestId(newRequestId());
            announce(`Asked ${job.model_name}. The suggestion will appear for review.`);
          },
        });
      }}
    >
      <h3 id={`${id}-ask`}>Ask for a suggestion</h3>
      <div className="form-row">
        <div className="field">
          <label htmlFor={`${id}-task`}>Task</label>
          <select id={`${id}-task`} value={task} onChange={(e) => setTask(e.target.value as AiTask)}>
            {TASKS.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
          <p className="hint">{TASKS.find((t) => t.value === task)?.help}</p>
        </div>
        <div className="field">
          <label htmlFor={`${id}-model`}>Model</label>
          <select id={`${id}-model`} value={choice} onChange={(e) => setChoice(e.target.value)}>
            <option value="default">
              {route
                ? `Default for ${task}: ${route.model_name} (${route.provider_label})`
                : `No default for ${task}: choose a model`}
            </option>
            {options.map((g) => (
              <optgroup
                key={g.provider.id}
                label={`${g.provider.label}: ${whereLabel(g.provider.local, g.provider.label)}`}
              >
                {g.models.map((m) => (
                  <option key={m} value={`${g.provider.id}::${m}`}>
                    {m}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          <p className="hint">
            {chosenProvider
              ? whereLabel(chosenProvider.local, chosenProvider.label)
              : route
                ? whereLabel(route.provider_local, route.provider_label)
                : options.length === 0
                  ? "No models yet. Add one in AI settings."
                  : "Pick a model, or set task defaults in AI settings."}{" "}
            <Link to="/ai-settings">AI settings</Link>
          </p>
        </div>
      </div>
      <div className="field">
        <label htmlFor={`${id}-instr`}>What should it do?</label>
        <textarea
          id={`${id}-instr`}
          rows={3}
          maxLength={4000}
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          placeholder="For example: one paragraph where the night shift arrives, in the same voice."
        />
      </div>
      {mode === "append" || mode === "insert_at" ? (
        <fieldset className="segmented compact">
          <legend>Where the text goes if you accept it</legend>
          <label>
            <input
              type="radio"
              name={`${id}-place`}
              checked={placement === "end"}
              onChange={() => setPlacement("end")}
            />
            End of the chapter
          </label>
          {task === "draft" ? (
            <label>
              <input
                type="radio"
                name={`${id}-place`}
                checked={placement === "cursor"}
                onChange={() => setPlacement("cursor")}
              />
              At the cursor
            </label>
          ) : null}
        </fieldset>
      ) : mode === "note" ? (
        <p className="hint">The answer is a note for you; it is not inserted into the chapter.</p>
      ) : (
        <p className="hint" aria-live="polite">
          {hasSelection
            ? `Replaces the selected passage (${selection.end - selection.start} characters).`
            : "Select the passage in the editor first."}
        </p>
      )}
      <fieldset className="knowledge-options">
        <legend>What the model may use</legend>
        <label className="inline-check">
          <input type="checkbox" checked={useSources} onChange={(e) => setUseSources(e.target.checked)} />
          This book's sources ({usable} enabled)
        </label>
        <label className="inline-check">
          <input type="checkbox" checked={useInterview} onChange={(e) => setUseInterview(e.target.checked)} />
          My interview answers
        </label>
        <p className="hint">
          Passages are sent as reference material only; the model must cite them, and anything it cites that
          it was not given is removed. <Link to={`/projects/${projectId}/knowledge`}>Manage sources</Link>
        </p>
      </fieldset>
      {task === "revise" ? (
        <div className="field">
          <label htmlFor={`${id}-voice`}>Rewrite in a voice (optional)</label>
          <select id={`${id}-voice`} value={voiceId} onChange={(e) => setVoiceId(e.target.value)}>
            <option value="">No, just follow my instruction</option>
            {(profiles.data ?? []).map((p) => (
              <option key={p.id} value={p.id} disabled={!p.style_guide_md.trim()}>
                {p.name}
                {p.style_guide_md.trim() ? "" : " (no style guide yet)"}
              </option>
            ))}
          </select>
          <p className="hint">
            Uses the style guide from <Link to="/voice">Author voice</Link>. You see the before and after and
            decide.
          </p>
        </div>
      ) : null}
      <div className="form-row">
        {task === "translate" ? (
          <div className="field">
            <label htmlFor={`${id}-lang`}>Into which language?</label>
            <input
              id={`${id}-lang`}
              value={language}
              maxLength={40}
              onChange={(e) => setLanguage(e.target.value)}
            />
          </div>
        ) : null}
        <div className="field">
          <label htmlFor={`${id}-max`}>Longest answer (tokens, optional)</label>
          <input
            id={`${id}-max`}
            type="number"
            min={16}
            max={200000}
            inputMode="numeric"
            value={maxTokens}
            onChange={(e) => setMaxTokens(e.target.value)}
          />
        </div>
      </div>

      {dirty && !locked ? (
        <div className="banner" role="status">
          <span>Save your changes first, so the AI works from the text you see.</span>
          <button type="button" className="btn btn-small btn-primary" onClick={onSave}>
            Save
          </button>
        </div>
      ) : null}
      {est ? (
        <EstimateLine
          est={est}
          privacy={info.data?.privacy_mode ?? "local_only"}
          onAllow={() => consent.grant.mutate(est.provider_id, { onSuccess: () => estimate.mutate(body) })}
          allowing={consent.grant.isPending}
        />
      ) : null}
      {estimate.error && ready ? <InlineError error={estimate.error} /> : null}
      {enqueue.error ? <InlineError error={enqueue.error} /> : null}
      <div className="page-actions">
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!ready || !!est?.blocked_reason || enqueue.isPending || locked}
        >
          {enqueue.isPending ? "Asking…" : "Ask"}
        </button>
      </div>
    </form>
  );
}

function EstimateLine({
  est,
  privacy,
  onAllow,
  allowing,
}: {
  est: Estimate;
  privacy: string;
  onAllow: () => void;
  allowing: boolean;
}) {
  const cost =
    est.cost_upper_bound === null || est.provider_local
      ? ""
      : `Up to ${est.cost_upper_bound} ${est.currency ?? ""} (estimate).`;
  return (
    <div className="estimate" role="status">
      <p>
        <strong>Estimate:</strong> about {est.input_tokens.toLocaleString()} tokens sent, up to{" "}
        {est.max_output_tokens.toLocaleString()} back. {cost} {est.cost_note}
        {est.context_clipped ? " Long chapter: only the part around your selection or the end is sent." : ""}
      </p>
      <p>
        {est.source_passages
          ? `${est.source_passages} passage(s) from your sources will be sent.`
          : "No source passages will be sent."}
        {est.interview_answers ? ` ${est.interview_answers} interview answer(s) will be sent.` : ""}
      </p>
      {est.blocked_reason ? (
        <div className="inline-error">
          <span>
            <strong>{est.blocked_reason}</strong>{" "}
            {privacy !== "cloud_allowed" ? (
              <>
                Choose a local model, or allow cloud AI in <Link to="/ai-settings">AI settings</Link>.
              </>
            ) : null}
          </span>
          {privacy === "cloud_allowed" ? (
            <button type="button" className="btn btn-small" onClick={onAllow} disabled={allowing}>
              Allow this book to use {est.provider_label}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function ChapterJobs({ projectId, chapterId }: { projectId: string; chapterId: string }) {
  const jobs = useJobs({ project_id: projectId, chapter_id: chapterId });
  const actions = useJobActions();
  const qc = useQueryClient();
  // A job that finishes in the background has produced a suggestion: load it into the review pane.
  const finished = (jobs.data ?? [])
    .filter((j) => j.status === "succeeded")
    .map((j) => j.id)
    .join(",");
  useEffect(() => {
    void qc.invalidateQueries({ queryKey: aiKeys.proposals(projectId, chapterId) });
  }, [finished, qc, projectId, chapterId]);
  const visible = (jobs.data ?? []).filter((j) => j.status !== "succeeded").slice(0, 5);
  if (visible.length === 0) return null;
  return (
    <section aria-label="Requests in progress or needing attention" className="ai-jobs">
      <h3>Requests</h3>
      <ul className="stack">
        {visible.map((j) => (
          <JobLine
            key={j.id}
            job={j}
            onCancel={() => actions.cancel.mutate(j.id)}
            onRetry={() => actions.retry.mutate(j.id)}
          />
        ))}
      </ul>
      <Link to="/jobs">All AI jobs and costs</Link>
    </section>
  );
}

export function JobLine({ job, onCancel, onRetry }: { job: Job; onCancel: () => void; onRetry: () => void }) {
  const active = ACTIVE.includes(job.status);
  const stage = job.cancel_requested && active ? STAGES.cancelling : (STAGES[job.stage] ?? job.stage);
  return (
    <li className="job-line" data-status={job.status}>
      <span>
        <strong>{TASKS.find((t) => t.value === job.task)?.label ?? job.task}</strong> with {job.model_name}:{" "}
        <span role="status">{stage}</span>
        {job.status === "running" && job.received_chars
          ? ` (${job.received_chars.toLocaleString()} characters so far)`
          : ""}
        {job.attempt > 1 ? ` · attempt ${job.attempt} of ${job.max_attempts}` : ""}
        {job.error_message ? <span className="job-error"> {job.error_message}</span> : null}
      </span>
      <span className="page-actions">
        {active && !job.cancel_requested ? (
          <button type="button" className="btn btn-small" onClick={onCancel}>
            Cancel
          </button>
        ) : null}
        {["failed", "cancelled", "interrupted"].includes(job.status) ? (
          <button type="button" className="btn btn-small" onClick={onRetry}>
            Retry
          </button>
        ) : null}
      </span>
    </li>
  );
}

const MODE_TEXT: Record<ProposalMode, string> = {
  append: "Will be added at the end of the chapter.",
  insert_at: "Will be inserted where the cursor was.",
  replace_selection: "Will replace this passage:",
  note: "A note for you. It is not inserted into the chapter.",
};

function ReviewPane({ projectId, chapterId, headNo, dirty, locked, onSave, proposals }: Props) {
  if (proposals.length === 0) return null;
  return (
    <section className="review-pane" aria-label="Suggestions to review">
      <h3>
        {proposals.length === 1 ? "1 suggestion to review" : `${proposals.length} suggestions to review`}
      </h3>
      {proposals.map((p) => (
        <ProposalCard
          key={p.id}
          proposal={p}
          projectId={projectId}
          chapterId={chapterId}
          headNo={headNo}
          dirty={dirty}
          locked={locked}
          onSave={onSave}
        />
      ))}
    </section>
  );
}

function ProposalCard({
  proposal: p,
  projectId,
  chapterId,
  headNo,
  dirty,
  locked,
  onSave,
}: {
  proposal: Proposal;
  projectId: string;
  chapterId: string;
  headNo: number;
  dirty: boolean;
  locked: boolean;
  onSave: () => void;
}) {
  const id = useId();
  const announce = useAnnounce();
  const actions = useProposalActions(projectId, chapterId);
  const [text, setText] = useState(p.payload_md);
  const prov = p.provenance as Record<string, string | undefined>;
  const local = prov.provider_kind === "ollama" || prov.provider_kind === "mock";
  const error = actions.accept.error ?? actions.reject.error;
  const note = p.mode === "note";
  return (
    <article className="proposal" aria-labelledby={`${id}-h`}>
      <header>
        <h4 id={`${id}-h`}>
          {TASKS.find((t) => t.value === prov.task)?.label ?? prov.task} by {prov.model}
        </h4>
        <p className="muted">
          {prov.provider_label} · {local ? "generated on this computer" : "generated in the cloud"} ·{" "}
          {relativeTime(p.created_at)}. AI text: check facts, names and quotations before you keep it.
        </p>
      </header>
      <p>{MODE_TEXT[p.mode]}</p>
      {p.mode === "replace_selection" && p.original_text ? (
        <blockquote className="original">{p.original_text}</blockquote>
      ) : null}
      <div className="field">
        <label htmlFor={`${id}-text`}>
          {note ? "Answer" : "Suggested text (you can edit it before accepting)"}
        </label>
        <textarea
          id={`${id}-text`}
          rows={Math.min(14, Math.max(4, text.split("\n").length + 1))}
          value={text}
          readOnly={note}
          onChange={(e) => setText(e.target.value)}
        />
      </div>
      <ParagraphSources provenance={p.provenance} />
      {!p.applicable && !note ? (
        <p className="inline-error" role="alert">
          {p.not_applicable_reason}
        </p>
      ) : null}
      {error && !(error instanceof ApiError && error.code === "conflict" && dirty) ? (
        <InlineError error={error} />
      ) : null}
      <div className="page-actions">
        {!note ? (
          dirty ? (
            <button type="button" className="btn btn-small" onClick={onSave} disabled={locked}>
              Save your changes to accept
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-primary btn-small"
              disabled={locked || !p.applicable || actions.accept.isPending || !text.trim()}
              onClick={() =>
                actions.accept.mutate(
                  {
                    id: p.id,
                    expected_head_no: headNo,
                    ...(text !== p.payload_md ? { edited_md: text } : {}),
                  },
                  {
                    onSuccess: (r) => announce(`Accepted. Saved as revision ${r.save.content.revision_no}.`),
                  },
                )
              }
            >
              {actions.accept.isPending ? "Accepting…" : "Accept as a new revision"}
            </button>
          )
        ) : null}
        <button
          type="button"
          className="btn btn-small"
          disabled={actions.reject.isPending}
          onClick={() =>
            actions.reject.mutate(p.id, {
              onSuccess: () => announce(note ? "Note dismissed" : "Suggestion rejected"),
            })
          }
        >
          {note ? "Dismiss" : "Reject"}
        </button>
      </div>
    </article>
  );
}

interface ParaSupport {
  label: string;
  kind: string;
  title: string;
  quote: string;
  located: boolean;
  source_id: string | null;
  chunk_id: string | null;
  citation_key: string | null;
  locator: string | null;
}
interface ParaInfo {
  index: number;
  preview: string;
  status: "supported" | "not_located" | "unverified";
  supports: ParaSupport[];
  dropped_labels: string[];
}

const PARA_STATUS: Record<ParaInfo["status"], string> = {
  supported: "Sources",
  not_located: "Cited, but the passage could not be located: check before keeping",
  unverified: "Unverified: no source supports this paragraph",
};

/** Per paragraph: the exact passages behind it, or an explicit "unverified" flag. */
function ParagraphSources({ provenance }: { provenance: Record<string, unknown> }) {
  const k = provenance.knowledge as { paragraphs?: ParaInfo[]; dropped_labels?: string[] } | undefined;
  const paras = k?.paragraphs ?? [];
  if (paras.length === 0) return null;
  return (
    <section className="para-sources" aria-label="Sources for each paragraph">
      {k?.dropped_labels?.length ? (
        <p className="inline-error" role="note">
          The model cited passages it was never given ({k.dropped_labels.join(", ")}). Those citations were
          removed.
        </p>
      ) : null}
      <ol>
        {paras.map((para) => (
          <li key={para.index} data-status={para.status}>
            <p className="para-preview">
              “{para.preview}
              {para.preview.length >= 160 ? "…" : ""}”
            </p>
            <p className={para.status === "supported" ? "support-ok" : "job-error"}>
              {PARA_STATUS[para.status]}
            </p>
            {para.supports.length ? (
              <ul>
                {para.supports.map((sup, i) => (
                  <li key={i}>
                    {sup.kind === "interview" ? (
                      <span>Your interview answer</span>
                    ) : sup.source_id ? (
                      <Link to={passageLink(sup.source_id, sup.chunk_id)}>
                        {sup.title}, {sup.locator}
                      </Link>
                    ) : (
                      sup.title
                    )}
                    {sup.located ? null : <span className="job-error"> (passage not located)</span>}
                    <blockquote className="quote">{sup.quote}</blockquote>
                  </li>
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
