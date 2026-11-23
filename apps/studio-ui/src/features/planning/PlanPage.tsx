import { useEffect, useId, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { newRequestId, useJobs, useProviders } from "../../api/ai";
import { ApiError } from "../../api/client";
import { useChapters, useProject } from "../../api/hooks";
import {
  FINDING_KINDS,
  FLAG_TEXT,
  useBrief,
  useBriefActions,
  useFindings,
  useOutlineActions,
  useOutlines,
  useResearchActions,
  useResearchProviders,
  useRunActions,
  useRuns,
  type Brief,
  type BriefIn,
  type Finding,
  type Outline,
  type PlanEstimate,
  type ResearchSearch,
} from "../../api/planning";
import { useAnnounce } from "../../components/Announcer";
import { PageHeader } from "../../components/Misc";
import { ErrorState, InlineError, Loading } from "../../components/States";
import type { OutlineNode } from "../../lib/outline";
import { OutlineEditor } from "./OutlineEditor";

const TABS = [
  ["brief", "Brief"],
  ["research", "Research"],
  ["outline", "Outline"],
  ["draft", "Draft chapters"],
] as const;
type Tab = (typeof TABS)[number][0];

/** Plan a book: brief, research, outline, then drafting. Each step waits for the author's approval. */
export function PlanPage() {
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find(([t]) => t === params.get("tab"))?.[0] ?? "brief") as Tab;
  const project = useProject(projectId);
  const brief = useBrief(projectId);
  if (brief.isError) return <ErrorState error={brief.error} onRetry={() => void brief.refetch()} />;
  if (!project.data || !brief.data) return <Loading label="Loading the plan" />;
  const archived = project.data.status === "archived";
  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to={`/projects/${projectId}`}>{project.data.title}</Link>
      </nav>
      <PageHeader
        title="Plan"
        intro="Brief, research and outline come first. AI drafts chapters only from an approved outline, and every draft is a suggestion you review."
      />
      <nav className="plan-tabs" aria-label="Planning steps">
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
      {tab === "brief" ? <BriefTab projectId={projectId} brief={brief.data} readOnly={archived} /> : null}
      {tab === "research" ? <ResearchTab projectId={projectId} readOnly={archived} /> : null}
      {tab === "outline" ? <OutlineTab projectId={projectId} brief={brief.data} readOnly={archived} /> : null}
      {tab === "draft" ? <DraftTab projectId={projectId} brief={brief.data} readOnly={archived} /> : null}
    </>
  );
}

export function ModelSelect({
  id,
  value,
  onChange,
  task,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  task: string;
}) {
  const providers = useProviders();
  return (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Default for “{task}” (AI settings)</option>
      {(providers.data ?? [])
        .filter((p) => p.enabled && p.models.length)
        .map((p) => (
          <optgroup key={p.id} label={`${p.label} (${p.local ? "on this computer" : "cloud"})`}>
            {p.models.map((m) => (
              <option key={m.name} value={`${p.id}::${m.name}`}>
                {m.name}
              </option>
            ))}
          </optgroup>
        ))}
    </select>
  );
}

function modelFields(choice: string): { provider_id?: string; model_name?: string } {
  if (!choice) return {};
  const [provider_id = "", model_name = ""] = choice.split("::");
  return { provider_id, model_name };
}

// ---------- brief ----------

function toIn(b: Brief): BriefIn {
  const { kind, genre, purpose, promise, tone, author_profile_id, desired_chapters, approval_preference, budget_cap,
    budget_currency, max_chapters_per_run, words_per_hour, target_reader, exclusions, value_proposition, arc_md,
    assumptions } = b; // prettier-ignore
  return { kind, genre, purpose, promise, tone, author_profile_id, desired_chapters, approval_preference, budget_cap,
    budget_currency, max_chapters_per_run, words_per_hour, target_reader, exclusions, value_proposition, arc_md,
    assumptions }; // prettier-ignore
}

function BriefTab({ projectId, brief, readOnly }: { projectId: string; brief: Brief; readOnly: boolean }) {
  const id = useId();
  const announce = useAnnounce();
  const actions = useBriefActions(projectId);
  const [v, setV] = useState<BriefIn>(toIn(brief));
  const [exclusions, setExclusions] = useState(brief.exclusions.join("\n"));
  const text = (k: keyof BriefIn) => ({
    id: `${id}-${k}`,
    value: (v[k] as string | null) ?? "",
    readOnly,
    onChange: (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value || null }),
  });
  const error = actions.save.error ?? actions.approve.error;
  return (
    <form
      className="form panel"
      aria-labelledby={`${id}-h`}
      onSubmit={(e) => {
        e.preventDefault();
        actions.save.mutate(
          {
            ...v,
            exclusions: exclusions
              .split("\n")
              .map((x) => x.trim())
              .filter(Boolean),
          },
          { onSuccess: (b) => announce(`Brief saved (version ${b.version}, ${b.status})`) },
        );
      }}
    >
      <h2 id={`${id}-h`}>
        Book brief{" "}
        <span className="tag">
          {brief.status === "approved"
            ? `Approved, version ${brief.version}`
            : `Draft, version ${brief.version}`}
        </span>
      </h2>
      <div className="form-row">
        <div className="field">
          <label htmlFor={`${id}-kind`}>Kind of book</label>
          <select
            id={`${id}-kind`}
            value={v.kind}
            disabled={readOnly}
            onChange={(e) => setV({ ...v, kind: e.target.value as BriefIn["kind"] })}
          >
            <option value="nonfiction">Nonfiction</option>
            <option value="manual">Manual</option>
            <option value="workbook">Workbook</option>
            <option value="memoir">Memoir</option>
            <option value="fiction">Fiction</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor={`${id}-genre`}>Genre</label>
          <input {...text("genre")} />
        </div>
        <div className="field">
          <label htmlFor={`${id}-tone`}>Tone</label>
          <input {...text("tone")} />
        </div>
      </div>
      <div className="field">
        <label htmlFor={`${id}-target_reader`}>Target reader</label>
        <textarea rows={2} {...text("target_reader")} />
      </div>
      <div className="field">
        <label htmlFor={`${id}-promise`}>Core promise</label>
        <textarea rows={2} {...text("promise")} />
      </div>
      <div className="field">
        <label htmlFor={`${id}-purpose`}>Purpose</label>
        <textarea rows={2} {...text("purpose")} />
      </div>
      <div className="field">
        <label htmlFor={`${id}-value_proposition`}>
          Value proposition: why this book rather than another
        </label>
        <textarea rows={2} {...text("value_proposition")} />
      </div>
      <div className="field">
        <label htmlFor={`${id}-excl`}>Leave out (one per line)</label>
        <textarea
          id={`${id}-excl`}
          rows={3}
          value={exclusions}
          readOnly={readOnly}
          onChange={(e) => setExclusions(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor={`${id}-arc_md`}>{v.kind === "fiction" ? "Plot arc" : "Teaching arc"}</label>
        <textarea rows={5} {...text("arc_md")} />
      </div>
      <fieldset>
        <legend>Assumptions, stated openly</legend>
        <p className="hint">
          Factual assumptions are things that must be true; creative ones are choices you have made.
        </p>
        {v.assumptions?.map((a, i) => (
          <div className="form-row" key={i}>
            <div className="field">
              <label htmlFor={`${id}-ak${i}`}>Kind</label>
              <select
                id={`${id}-ak${i}`}
                value={a.kind}
                disabled={readOnly}
                onChange={(e) =>
                  setV({
                    ...v,
                    assumptions: v.assumptions!.map((x, j) =>
                      j === i ? { ...x, kind: e.target.value as "factual" | "creative" } : x,
                    ),
                  })
                }
              >
                <option value="factual">Factual</option>
                <option value="creative">Creative</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor={`${id}-at${i}`}>Assumption</label>
              <input
                id={`${id}-at${i}`}
                value={a.text}
                readOnly={readOnly}
                onChange={(e) =>
                  setV({
                    ...v,
                    assumptions: v.assumptions!.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)),
                  })
                }
              />
            </div>
            <button
              type="button"
              className="btn btn-small"
              disabled={readOnly}
              onClick={() => setV({ ...v, assumptions: v.assumptions!.filter((_, j) => j !== i) })}
            >
              Remove
            </button>
          </div>
        ))}
        <button
          type="button"
          className="btn btn-small"
          disabled={readOnly}
          onClick={() =>
            setV({ ...v, assumptions: [...(v.assumptions ?? []), { kind: "factual", text: "" }] })
          }
        >
          Add an assumption
        </button>
      </fieldset>
      <div className="form-row">
        <div className="field">
          <label htmlFor={`${id}-chapters`}>Desired chapters</label>
          <input
            id={`${id}-chapters`}
            type="number"
            min={1}
            max={200}
            readOnly={readOnly}
            value={v.desired_chapters ?? ""}
            onChange={(e) => setV({ ...v, desired_chapters: e.target.value ? Number(e.target.value) : null })}
          />
        </div>
        <div className="field">
          <label htmlFor={`${id}-cap`}>Budget cap per run</label>
          <input
            id={`${id}-cap`}
            inputMode="decimal"
            placeholder="No cap"
            readOnly={readOnly}
            value={v.budget_cap ?? ""}
            onChange={(e) =>
              setV({ ...v, budget_cap: e.target.value || null, budget_currency: v.budget_currency ?? "USD" })
            }
          />
        </div>
        <div className="field">
          <label htmlFor={`${id}-cur`}>Currency</label>
          <input
            id={`${id}-cur`}
            maxLength={3}
            readOnly={readOnly}
            value={v.budget_currency ?? ""}
            onChange={(e) => setV({ ...v, budget_currency: e.target.value.toUpperCase() || null })}
          />
        </div>
        <div className="field">
          <label htmlFor={`${id}-limit`}>Most chapters per run</label>
          <input
            id={`${id}-limit`}
            type="number"
            min={1}
            max={200}
            readOnly={readOnly}
            value={v.max_chapters_per_run ?? 10}
            onChange={(e) => setV({ ...v, max_chapters_per_run: Number(e.target.value) })}
          />
        </div>
        <div className="field">
          <label htmlFor={`${id}-wph`}>Your drafting speed (words per hour)</label>
          <input
            id={`${id}-wph`}
            type="number"
            min={50}
            max={10000}
            readOnly={readOnly}
            value={v.words_per_hour ?? 500}
            onChange={(e) => setV({ ...v, words_per_hour: Number(e.target.value) })}
          />
        </div>
      </div>
      {error ? <InlineError error={error} /> : null}
      {!readOnly ? (
        <div className="page-actions">
          <button type="submit" className="btn btn-primary" disabled={actions.save.isPending}>
            Save brief
          </button>
          <button
            type="button"
            className="btn"
            disabled={brief.status === "approved" || actions.approve.isPending}
            onClick={() => actions.approve.mutate(undefined, { onSuccess: () => announce("Brief approved") })}
          >
            Approve brief
          </button>
        </div>
      ) : null}
    </form>
  );
}

// ---------- research ----------

function FindingItem({ f, projectId, readOnly }: { f: Finding; projectId: string; readOnly: boolean }) {
  const actions = useResearchActions(projectId);
  return (
    <li className="finding" data-evidence={f.evidence}>
      <p className="finding-text">{f.text}</p>
      <p className="muted">
        {FINDING_KINDS.find((k) => k.value === f.kind)?.label} ·{" "}
        {f.origin === "author"
          ? "added by you"
          : f.origin === "provider"
            ? `from ${f.source_title ?? f.provider}`
            : "AI brainstorm"}
        {f.source_url ? (
          <>
            {" · "}
            <a href={f.source_url} target="_blank" rel="noreferrer noopener">
              {f.source_title ?? "source"}
            </a>
          </>
        ) : f.source_title && f.origin === "author" ? (
          ` · ${f.source_title}`
        ) : (
          ""
        )}
        {f.source_date ? ` · dated ${f.source_date}` : ""}
        {f.retrieved_at ? ` · captured ${f.retrieved_at.slice(0, 10)}` : ""}
      </p>
      {f.flags.length ? (
        <ul className="flags">
          {f.flags.map((x) => (
            <li key={x}>{FLAG_TEXT[x] ?? x}</li>
          ))}
        </ul>
      ) : null}
      {!readOnly ? (
        <div className="page-actions">
          <label className="inline-check">
            <input
              type="checkbox"
              checked={f.selected}
              onChange={(e) => actions.patch.mutate({ id: f.id, selected: e.target.checked })}
            />
            Use for the outline
          </label>
          <button
            type="button"
            className="btn btn-small"
            onClick={() => actions.patch.mutate({ id: f.id, archived: true })}
          >
            Archive
          </button>
        </div>
      ) : null}
    </li>
  );
}

function ResearchTab({ projectId, readOnly }: { projectId: string; readOnly: boolean }) {
  const id = useId();
  const announce = useAnnounce();
  const findings = useFindings(projectId);
  const providers = useResearchProviders();
  const actions = useResearchActions(projectId);
  const [provider, setProvider] = useState<"openlibrary" | "mock">("openlibrary");
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<ResearchSearch | null>(null);
  const [form, setForm] = useState({
    kind: "note" as Finding["kind"],
    text: "",
    source_title: "",
    source_url: "",
    source_date: "",
  });
  const [model, setModel] = useState("");
  const measured = (findings.data ?? []).filter((f) => f.evidence === "measured");
  const heuristic = (findings.data ?? []).filter((f) => f.evidence !== "measured");
  return (
    <div className="two-col">
      <div className="stack">
        <section className="panel" aria-labelledby={`${id}-ev`}>
          <h2 id={`${id}-ev`}>Measured evidence</h2>
          <p className="hint">
            Only findings with a named source. Sales ranks, market size, demand, competition scores and search
            volumes are never shown: no licensed source for them is connected.
          </p>
          {measured.length ? (
            <ul className="findings">
              {measured.map((f) => (
                <FindingItem key={f.id} f={f} projectId={projectId} readOnly={readOnly} />
              ))}
            </ul>
          ) : (
            <p className="muted">None yet.</p>
          )}
        </section>
        <section className="panel" aria-labelledby={`${id}-heu`}>
          <h2 id={`${id}-heu`}>Notes, ideas and comparable titles (heuristic)</h2>
          {heuristic.length ? (
            <ul className="findings">
              {heuristic.map((f) => (
                <FindingItem key={f.id} f={f} projectId={projectId} readOnly={readOnly} />
              ))}
            </ul>
          ) : (
            <p className="muted">None yet.</p>
          )}
        </section>
      </div>
      <div className="stack">
        {!readOnly ? (
          <form
            className="form panel"
            aria-labelledby={`${id}-add`}
            onSubmit={(e) => {
              e.preventDefault();
              actions.add.mutate(
                {
                  kind: form.kind,
                  text: form.text,
                  source_title: form.source_title || null,
                  source_url: form.source_url || null,
                  source_date: form.source_date || null,
                  meta: {},
                },
                {
                  onSuccess: () => {
                    setForm({ ...form, text: "", source_title: "", source_url: "", source_date: "" });
                    announce("Finding added");
                  },
                },
              );
            }}
          >
            <h2 id={`${id}-add`}>Add a finding</h2>
            <div className="field">
              <label htmlFor={`${id}-kind`}>Kind</label>
              <select
                id={`${id}-kind`}
                value={form.kind}
                onChange={(e) => setForm({ ...form, kind: e.target.value as Finding["kind"] })}
              >
                {FINDING_KINDS.map((k) => (
                  <option key={k.value} value={k.value}>
                    {k.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor={`${id}-text`}>Finding</label>
              <textarea
                id={`${id}-text`}
                rows={3}
                value={form.text}
                onChange={(e) => setForm({ ...form, text: e.target.value })}
              />
            </div>
            <div className="form-row">
              <div className="field">
                <label htmlFor={`${id}-st`}>Source name</label>
                <input
                  id={`${id}-st`}
                  value={form.source_title}
                  onChange={(e) => setForm({ ...form, source_title: e.target.value })}
                />
              </div>
              <div className="field">
                <label htmlFor={`${id}-su`}>Web address</label>
                <input
                  id={`${id}-su`}
                  type="url"
                  value={form.source_url}
                  onChange={(e) => setForm({ ...form, source_url: e.target.value })}
                />
              </div>
              <div className="field">
                <label htmlFor={`${id}-sd`}>Date of the source</label>
                <input
                  id={`${id}-sd`}
                  placeholder="2025-03"
                  value={form.source_date}
                  onChange={(e) => setForm({ ...form, source_date: e.target.value })}
                />
              </div>
            </div>
            {actions.add.error ? <InlineError error={actions.add.error} /> : null}
            <div className="page-actions">
              <button type="submit" className="btn btn-primary" disabled={!form.text.trim()}>
                Add finding
              </button>
            </div>
          </form>
        ) : null}
        <section className="panel" aria-labelledby={`${id}-search`}>
          <h2 id={`${id}-search`}>Search public catalogues</h2>
          <p className="hint">
            {(providers.data ?? [])
              .map((p) => `${p.label}: ${p.available ? "ready" : p.enabled ? p.unavailable_reason : "off"}`)
              .join(". ")}
            . <Link to="/ai-settings">Research settings</Link>
          </p>
          <form
            className="search-row"
            role="search"
            onSubmit={(e) => {
              e.preventDefault();
              actions.search.mutate(
                { provider, query },
                { onSuccess: setResult, onError: () => setResult(null) },
              );
            }}
          >
            <label htmlFor={`${id}-prov`} className="visually-hidden">
              Catalogue
            </label>
            <select
              id={`${id}-prov`}
              value={provider}
              onChange={(e) => setProvider(e.target.value as typeof provider)}
            >
              {(providers.data ?? []).map((p) => (
                <option key={p.kind} value={p.kind}>
                  {p.label}
                </option>
              ))}
            </select>
            <label htmlFor={`${id}-q`} className="visually-hidden">
              Search words
            </label>
            <input id={`${id}-q`} type="search" value={query} onChange={(e) => setQuery(e.target.value)} />
            <button type="submit" className="btn" disabled={query.trim().length < 2 || readOnly}>
              Search
            </button>
          </form>
          {actions.search.error ? <InlineError error={actions.search.error} /> : null}
          {result ? (
            <>
              <p className="hint">{result.note}</p>
              <ol className="hits">
                {result.hits.map((h) => (
                  <li key={h.index} className="hit">
                    <p className="hit-head">
                      {h.url ? (
                        <a href={h.url} target="_blank" rel="noreferrer noopener">
                          {h.title}
                        </a>
                      ) : (
                        h.title
                      )}{" "}
                      <span className="muted">
                        {h.authors.join(", ")}
                        {h.year ? ` (${h.year})` : ""}
                      </span>
                    </p>
                    <button
                      type="button"
                      className="btn btn-small"
                      onClick={() =>
                        actions.save.mutate(
                          { query_id: result.query_id, index: h.index, kind: "competitor" },
                          { onSuccess: () => announce("Saved as a comparable title") },
                        )
                      }
                    >
                      Save as comparable title
                    </button>
                  </li>
                ))}
              </ol>
            </>
          ) : null}
        </section>
        {!readOnly ? (
          <section className="panel" aria-labelledby={`${id}-ai`}>
            <h2 id={`${id}-ai`}>Brainstorm with AI</h2>
            <p className="hint">
              Ideas only, never evidence. Any statement about sales, rankings, demand, competition or search
              volume is removed.
            </p>
            <div className="field">
              <label htmlFor={`${id}-model`}>Model</label>
              <ModelSelect id={`${id}-model`} value={model} onChange={setModel} task="research" />
            </div>
            <div className="page-actions">
              {(["topics", "queries", "keywords"] as const).map((what) => (
                <button
                  key={what}
                  type="button"
                  className="btn btn-small"
                  disabled={actions.ideas.isPending}
                  onClick={() =>
                    actions.ideas.mutate(
                      { what, instruction: "", ...modelFields(model), client_request_id: newRequestId() },
                      { onSuccess: () => announce(`Asked for ${what}. They appear here when ready.`) },
                    )
                  }
                >
                  {what === "topics"
                    ? "Find topics"
                    : what === "queries"
                      ? "Draft search queries"
                      : "Brainstorm KDP keywords"}
                </button>
              ))}
            </div>
            {actions.ideas.error ? <InlineError error={actions.ideas.error} /> : null}
            <PendingJobs projectId={projectId} />
          </section>
        ) : null}
      </div>
    </div>
  );
}

/** While planning jobs run, refresh their results when they finish. */
function PendingJobs({ projectId }: { projectId: string }) {
  const jobs = useJobs({ project_id: projectId });
  const findings = useFindings(projectId);
  const outlines = useOutlines(projectId);
  const active = (jobs.data ?? []).filter(
    (j) => !j.chapter_id && (j.status === "queued" || j.status === "running"),
  );
  const failed = (jobs.data ?? []).filter((j) => !j.chapter_id && j.status === "failed").slice(0, 2);
  const doneIds = (jobs.data ?? [])
    .filter((j) => !j.chapter_id && j.status === "succeeded")
    .map((j) => j.id)
    .join();
  useEffect(() => {
    void findings.refetch();
    void outlines.refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doneIds]);
  if (!active.length && !failed.length) return null;
  return (
    <ul className="stack" aria-live="polite">
      {active.map((j) => (
        <li key={j.id} className="muted">
          Working: {j.task} with {j.model_name} ({j.stage.replace(/_/g, " ")})
        </li>
      ))}
      {failed.map((j) => (
        <li key={j.id} className="job-error">
          {j.task} failed: {j.error_message} <Link to="/jobs">Details</Link>
        </li>
      ))}
    </ul>
  );
}

// ---------- outline ----------

const STATUS_LABEL: Record<Outline["status"], string> = {
  draft: "Your draft",
  proposed: "AI proposal",
  approved: "Approved",
  superseded: "Superseded",
  rejected: "Rejected",
};

function OutlineTab({ projectId, brief, readOnly }: { projectId: string; brief: Brief; readOnly: boolean }) {
  const id = useId();
  const announce = useAnnounce();
  const outlines = useOutlines(projectId);
  const actions = useOutlineActions(projectId);
  const [model, setModel] = useState("");
  const [instruction, setInstruction] = useState("");
  const draft = outlines.data?.find((o) => o.status === "draft");
  const [nodes, setNodes] = useState<OutlineNode[] | null>(null);
  const [seen, setSeen] = useState<string | null>(null);
  const key = draft ? `${draft.id}:${draft.updated_at}` : null;
  if (key !== seen) {
    setSeen(key);
    setNodes(draft ? (draft.nodes as unknown as OutlineNode[]) : null);
  }
  const proposals = (outlines.data ?? []).filter((o) => o.status === "proposed");
  const approved = outlines.data?.find((o) => o.status === "approved");
  const error =
    actions.saveDraft.error ??
    actions.approve.error ??
    actions.apply.error ??
    actions.generate.error ??
    actions.edit.error;
  if (!outlines.data) return <Loading label="Loading outlines" />;
  return (
    <div className="stack">
      {error ? <InlineError error={error} /> : null}
      {!readOnly ? (
        <section className="panel" aria-labelledby={`${id}-gen`}>
          <h2 id={`${id}-gen`}>Ask AI for an outline</h2>
          <p className="hint">
            Uses the brief and the research findings marked “Use for the outline”. The result is a new
            proposal: your draft and any approved outline stay as they are, and entries you locked are kept.
          </p>
          <div className="form-row">
            <div className="field">
              <label htmlFor={`${id}-model`}>Model</label>
              <ModelSelect id={`${id}-model`} value={model} onChange={setModel} task="outline" />
            </div>
            <div className="field">
              <label htmlFor={`${id}-instr`}>Anything else? (optional)</label>
              <input
                id={`${id}-instr`}
                value={instruction}
                maxLength={2000}
                onChange={(e) => setInstruction(e.target.value)}
              />
            </div>
          </div>
          <div className="page-actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={actions.generate.isPending}
              onClick={() =>
                actions.generate.mutate(
                  { instruction, research_ids: [], ...modelFields(model), client_request_id: newRequestId() },
                  { onSuccess: () => announce("Asked for an outline proposal") },
                )
              }
            >
              Propose an outline
            </button>
          </div>
          <PendingJobs projectId={projectId} />
        </section>
      ) : null}

      {proposals.map((o) => (
        <section key={o.id} className="panel outline-proposal" aria-labelledby={`${id}-p${o.version_no}`}>
          <h2 id={`${id}-p${o.version_no}`}>AI proposal, version {o.version_no}</h2>
          <OutlineView outline={o} />
          {!readOnly ? (
            <div className="page-actions">
              <button
                type="button"
                className="btn btn-primary"
                onClick={() =>
                  actions.approve.mutate(o.id, {
                    onSuccess: () => announce(`Approved outline version ${o.version_no}`),
                  })
                }
              >
                Approve this outline
              </button>
              <button
                type="button"
                className="btn"
                onClick={() =>
                  actions.edit.mutate(o.id, {
                    onSuccess: () => announce("Copied into your draft for editing"),
                  })
                }
              >
                Edit it first
              </button>
              <button type="button" className="btn" onClick={() => actions.reject.mutate(o.id)}>
                Reject
              </button>
            </div>
          ) : null}
        </section>
      ))}

      <section className="panel" aria-labelledby={`${id}-draft`}>
        <h2 id={`${id}-draft`}>Your outline draft</h2>
        {nodes ? (
          <>
            <OutlineEditor
              nodes={nodes}
              onChange={setNodes}
              fiction={brief.kind === "fiction"}
              wordsPerHour={brief.words_per_hour}
            />
            {!readOnly ? (
              <div className="page-actions">
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={actions.saveDraft.isPending}
                  onClick={() =>
                    actions.saveDraft.mutate(
                      { nodes: nodes as never, based_on_id: draft?.based_on_id ?? null },
                      { onSuccess: () => announce("Outline draft saved") },
                    )
                  }
                >
                  Save draft
                </button>
                <button
                  type="button"
                  className="btn"
                  disabled={!draft || actions.approve.isPending}
                  onClick={() =>
                    draft &&
                    actions.saveDraft.mutate(
                      { nodes: nodes as never, based_on_id: draft.based_on_id ?? null },
                      {
                        onSuccess: (d) =>
                          actions.approve.mutate(d.id, { onSuccess: () => announce("Outline approved") }),
                      },
                    )
                  }
                >
                  Save and approve
                </button>
              </div>
            ) : null}
          </>
        ) : (
          <div className="page-actions">
            <p className="muted">No draft. Edit a proposal or the approved outline, or start one by hand.</p>
            {!readOnly ? (
              <button
                type="button"
                className="btn"
                onClick={() =>
                  setNodes([
                    {
                      kind: "chapter",
                      title: "Chapter one",
                      goal: "",
                      target_words: null,
                      locked: false,
                      notes: "",
                      requirements: {},
                      children: [],
                    },
                  ])
                }
              >
                Start an outline by hand
              </button>
            ) : null}
          </div>
        )}
      </section>

      {approved ? (
        <section className="panel" aria-labelledby={`${id}-ap`}>
          <h2 id={`${id}-ap`}>Approved outline, version {approved.version_no}</h2>
          <OutlineView outline={approved} />
          <p className="hint">
            {approved.applied_at
              ? "Applied to the manuscript. Applying again updates titles and order of chapters without text."
              : "Not applied yet. Applying creates empty chapters; chapters with text, locked or approved chapters are never changed."}
          </p>
          {!readOnly ? (
            <div className="page-actions">
              <button
                type="button"
                className="btn btn-primary"
                disabled={actions.apply.isPending}
                onClick={() =>
                  actions.apply.mutate(approved.id, {
                    onSuccess: (r) =>
                      announce(`Applied: ${(r.report.created as string[]).length} new chapters`),
                  })
                }
              >
                Apply to manuscript
              </button>
              <button type="button" className="btn" onClick={() => actions.edit.mutate(approved.id)}>
                Edit as a new draft
              </button>
            </div>
          ) : null}
          {approved.apply_report ? (
            <ApplyReport report={approved.apply_report as Record<string, unknown>} />
          ) : null}
        </section>
      ) : null}

      <details>
        <summary>All versions ({outlines.data.length})</summary>
        <ul>
          {outlines.data.map((o) => (
            <li key={o.id}>
              Version {o.version_no}: {STATUS_LABEL[o.status]} ({o.origin === "author" ? "by you" : "AI"}),{" "}
              {o.totals.chapters as number} chapters
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

function OutlineView({ outline }: { outline: Outline }) {
  const render = (nodes: Record<string, unknown>[]) => (
    <ol className="outline-view">
      {nodes.map((n) => (
        <li key={String(n.id)}>
          <strong>{String(n.title)}</strong>
          {n.locked ? <span className="tag"> Locked</span> : null}
          {n.target_words ? (
            <span className="muted"> · {Number(n.target_words).toLocaleString()} words</span>
          ) : null}
          {n.goal ? <p className="muted">{String(n.goal)}</p> : null}
          {(n.children as Record<string, unknown>[]).length
            ? render(n.children as Record<string, unknown>[])
            : null}
        </li>
      ))}
    </ol>
  );
  const t = outline.totals as Record<string, unknown>;
  return (
    <>
      <p className="hint">
        {String(t.chapters)} chapters, {Number(t.target_words).toLocaleString()} target words, about{" "}
        {String(t.estimated_writing_hours)} hours of drafting. {String(t.writing_hours_basis)}
      </p>
      {render(outline.nodes as Record<string, unknown>[])}
    </>
  );
}

function ApplyReport({ report }: { report: Record<string, unknown> }) {
  const rows: [string, string][] = [
    ["created", "New empty chapters"],
    ["updated", "Renamed or moved"],
    ["restored", "Restored from archive"],
    ["archived_empty", "Archived (they were empty)"],
    ["kept_not_in_outline", "Kept: no longer in the outline but they have text"],
    ["skipped_locked", "Left as they are: locked or approved"],
    ["manual_kept", "Kept: chapters you added by hand"],
  ];
  return (
    <dl className="apply-report">
      {rows
        .filter(([k]) => (report[k] as string[] | undefined)?.length)
        .map(([k, label]) => (
          <div key={k}>
            <dt>{label}</dt>
            <dd>{(report[k] as string[]).join(", ")}</dd>
          </div>
        ))}
    </dl>
  );
}

// ---------- drafting ----------

function DraftTab({ projectId, brief, readOnly }: { projectId: string; brief: Brief; readOnly: boolean }) {
  const id = useId();
  const announce = useAnnounce();
  const chapters = useChapters(projectId);
  const runs = useRuns(projectId);
  const actions = useRunActions(projectId);
  const [mode, setMode] = useState<"one_chapter" | "entire_book">(
    brief.approval_preference === "review_outline_then_batch" ? "entire_book" : "one_chapter",
  );
  const [chapterId, setChapterId] = useState("");
  const [model, setModel] = useState("");
  const [useSources, setUseSources] = useState(true);
  const [est, setEst] = useState<PlanEstimate | null>(null);
  const body = {
    mode,
    chapter_ids: mode === "one_chapter" && chapterId ? [chapterId] : [],
    use_sources: useSources,
    use_interview: brief.kind === "memoir",
    ...modelFields(model),
  };
  const blockedByOutline =
    actions.estimate.error instanceof ApiError &&
    actions.estimate.error.problem.reason === "outline_not_approved";
  return (
    <div className="stack">
      <section className="panel" aria-labelledby={`${id}-h`}>
        <h2 id={`${id}-h`}>Draft chapters from the approved outline</h2>
        <p className="hint">
          Every draft arrives as a suggestion in the chapter for you to accept, edit or reject. Locked and
          approved chapters are skipped, and chapters that already have text are skipped when drafting the
          whole book.
        </p>
        <fieldset className="segmented">
          <legend>What to draft</legend>
          <label>
            <input
              type="radio"
              name={`${id}-mode`}
              checked={mode === "one_chapter"}
              onChange={() => {
                setMode("one_chapter");
                setEst(null);
              }}
            />
            One chapter
          </label>
          <label>
            <input
              type="radio"
              name={`${id}-mode`}
              checked={mode === "entire_book"}
              onChange={() => {
                setMode("entire_book");
                setEst(null);
              }}
            />
            Every eligible chapter
          </label>
        </fieldset>
        <div className="form-row">
          {mode === "one_chapter" ? (
            <div className="field">
              <label htmlFor={`${id}-ch`}>Chapter</label>
              <select
                id={`${id}-ch`}
                value={chapterId}
                onChange={(e) => {
                  setChapterId(e.target.value);
                  setEst(null);
                }}
              >
                <option value="">Choose a chapter</option>
                {(chapters.data ?? [])
                  .filter((c) => c.kind === "chapter")
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.title}
                    </option>
                  ))}
              </select>
            </div>
          ) : null}
          <div className="field">
            <label htmlFor={`${id}-model`}>Model</label>
            <ModelSelect
              id={`${id}-model`}
              value={model}
              onChange={(v) => {
                setModel(v);
                setEst(null);
              }}
              task="draft"
            />
          </div>
        </div>
        <label className="inline-check">
          <input
            type="checkbox"
            checked={useSources}
            onChange={(e) => {
              setUseSources(e.target.checked);
              setEst(null);
            }}
          />
          Use this book's sources
        </label>
        <div className="page-actions">
          <button
            type="button"
            className="btn"
            disabled={mode === "one_chapter" && !chapterId}
            onClick={() =>
              actions.estimate.mutate(
                { ...body, client_request_id: "estimate-only" },
                { onSuccess: setEst, onError: () => setEst(null) },
              )
            }
          >
            Estimate
          </button>
        </div>
        {blockedByOutline ? (
          <p className="inline-error" role="alert">
            Approve an outline and apply it to the manuscript first (Outline tab).
          </p>
        ) : actions.estimate.error ? (
          <InlineError error={actions.estimate.error} />
        ) : null}
        {est ? <EstimateTable est={est} /> : null}
        {est && !readOnly ? (
          <div className="page-actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={!!est.blocked_reason || actions.start.isPending}
              onClick={() =>
                actions.start.mutate(
                  { ...body, client_request_id: newRequestId() },
                  {
                    onSuccess: (r) => {
                      setEst(null);
                      announce(`Started: ${r.job_ids.length} chapter draft(s) queued for review`);
                    },
                  },
                )
              }
            >
              Start drafting {est.eligible_count} chapter(s)
            </button>
          </div>
        ) : null}
        {actions.start.error ? <InlineError error={actions.start.error} /> : null}
      </section>
      <section className="panel" aria-labelledby={`${id}-runs`}>
        <h2 id={`${id}-runs`}>Runs</h2>
        {(runs.data ?? []).length === 0 ? (
          <p className="muted">No runs yet.</p>
        ) : (
          <ul className="runs">
            {runs.data!.map((r) => (
              <li key={r.id}>
                <strong>{r.mode === "entire_book" ? "Whole book" : "One chapter"}</strong>: {r.status},{" "}
                {r.job_ids.length} chapter(s), spent {r.spent}
                {r.currency ? ` ${r.currency}` : ""}
                {r.budget_cap ? ` of a ${r.budget_cap} ${r.currency ?? ""} cap` : ""}
                {r.unknown_cost_calls ? `, ${r.unknown_cost_calls} with unknown cost` : ""}
                {r.stop_reason ? <p className="job-error">{r.stop_reason}</p> : null}
                {r.skipped.length ? (
                  <p className="muted">
                    Skipped: {r.skipped.map((x) => `${x.title} (${x.reason})`).join("; ")}
                  </p>
                ) : null}
                <div className="page-actions">
                  <Link to="/jobs">Progress in AI jobs</Link>
                  {r.status === "running" ? (
                    <button type="button" className="btn btn-small" onClick={() => actions.stop.mutate(r.id)}>
                      Stop
                    </button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function EstimateTable({ est }: { est: PlanEstimate }) {
  return (
    <div className="estimate" role="status">
      <p>
        <strong>Estimate:</strong> {est.eligible_count} chapter(s) with {est.model_name} (
        {est.provider_local ? "on this computer" : `cloud: ${est.provider_label}`}).{" "}
        {est.cost_upper_bound === null
          ? "Cost unknown."
          : est.provider_local
            ? ""
            : `Up to ${est.cost_upper_bound} ${est.currency ?? ""}.`}{" "}
        {est.cost_note} {est.minutes_estimate !== null ? `About ${est.minutes_estimate} minutes. ` : ""}
        {est.time_note} Limit: {est.chapter_limit} chapters per run
        {est.budget_cap ? `; budget cap ${est.budget_cap} ${est.budget_currency ?? ""}` : ""}.
      </p>
      {est.blocked_reason ? <p className="inline-error">{est.blocked_reason}</p> : null}
      <table className="data-table">
        <caption className="visually-hidden">Chapters in this run</caption>
        <thead>
          <tr>
            <th scope="col">Chapter</th>
            <th scope="col">Target words</th>
            <th scope="col">Tokens in / out (max)</th>
            <th scope="col">Will draft?</th>
          </tr>
        </thead>
        <tbody>
          {est.chapters.map((c) => (
            <tr key={c.chapter_id}>
              <th scope="row">{c.title}</th>
              <td>{c.target_words?.toLocaleString() ?? "not set"}</td>
              <td>
                {c.input_tokens.toLocaleString()} / {c.max_output_tokens.toLocaleString()}
              </td>
              <td>{c.eligible ? "Yes" : c.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
