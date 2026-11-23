import { useId, useState } from "react";
import { Link, useParams } from "react-router";
import { useProject } from "../../api/hooks";
import { useCitations, useClaimActions, useClaims, type Claim, type SearchHit } from "../../api/knowledge";
import { useAnnounce } from "../../components/Announcer";
import { PageHeader } from "../../components/Misc";
import { EmptyState, ErrorState, InlineError, Loading } from "../../components/States";
import { passageLink, SearchPanel } from "./parts";

const SUPPORT: Record<Claim["support_status"], string> = {
  supported: "Supported by a located passage",
  not_located: "Cited, but the passage could not be located: check it",
  unverified: "Unverified: no source",
};
const REVIEW: Record<Claim["review_state"], string> = {
  needs_review: "Needs review",
  verified: "Verified by you",
  disputed: "Disputed",
};

/** The evidence ledger: statements in the book and the exact passages behind them, kept apart from the prose. */
export function EvidencePage() {
  const { projectId = "" } = useParams();
  const id = useId();
  const project = useProject(projectId);
  const [showProposed, setShowProposed] = useState(false);
  const claims = useClaims(projectId, showProposed);
  const citations = useCitations(projectId);
  if (claims.isError) return <ErrorState error={claims.error} onRetry={() => void claims.refetch()} />;
  if (!project.data || !claims.data) return <Loading label="Loading the evidence ledger" />;
  const archived = project.data.status === "archived";
  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to={`/projects/${projectId}`}>{project.data.title}</Link>
      </nav>
      <PageHeader
        title="Evidence ledger"
        intro="Every statement that cites a source, with the exact passage behind it. AI-cited claims arrive here when you accept a suggestion; you can add your own."
        actions={
          <Link className="btn" to={`/projects/${projectId}/knowledge`}>
            Sources
          </Link>
        }
      />
      <div className="two-col">
        <section className="stack" aria-labelledby={`${id}-claims`}>
          <h2 id={`${id}-claims`} className="visually-hidden">
            Claims
          </h2>
          <label className="inline-check">
            <input
              type="checkbox"
              checked={showProposed}
              onChange={(e) => setShowProposed(e.target.checked)}
            />
            Include claims in suggestions not yet accepted
          </label>
          {claims.data.length === 0 ? (
            <EmptyState title="No claims yet">
              Accept an AI suggestion that cites your sources, or add a claim yourself.
            </EmptyState>
          ) : (
            <ul className="claims">
              {claims.data.map((c) => (
                <ClaimItem key={c.id} claim={c} projectId={projectId} readOnly={archived} />
              ))}
            </ul>
          )}
        </section>
        <div className="stack">
          {!archived ? <AddClaim projectId={projectId} /> : null}
          <section className="panel" aria-labelledby={`${id}-cites`}>
            <h2 id={`${id}-cites`}>Sources cited in the text</h2>
            {citations.data && citations.data.length > 0 ? (
              <ul className="citations">
                {citations.data.map((c) => (
                  <li key={c.id}>
                    <code>@{c.id}</code> <Link to={passageLink(c.source_id)}>{c.title}</Link>
                    {c.author.length ? `, ${c.author.join("; ")}` : ""}
                    {c.issued ? ` (${c.issued})` : ""} · {c.cited_in_chapters} chapter(s)
                    {!c.author.length && !c.issued ? (
                      <span className="muted"> · author and year not entered</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">No sources are cited in the chapters yet.</p>
            )}
          </section>
        </div>
      </div>
    </>
  );
}

function ClaimItem({
  claim: c,
  projectId,
  readOnly,
}: {
  claim: Claim;
  projectId: string;
  readOnly: boolean;
}) {
  const id = useId();
  const actions = useClaimActions(projectId);
  return (
    <li className="claim" data-support={c.support_status}>
      <p className="claim-text">{c.text}</p>
      <p className="muted">
        {c.origin === "author" ? "Added by you" : "From an accepted AI suggestion"}
        {c.chapter_title ? ` · ${c.chapter_title}` : ""}
        {c.lifecycle === "proposed" ? " · in a suggestion not yet accepted" : ""}
      </p>
      <p className={c.support_status === "supported" ? "support-ok" : "job-error"}>
        {SUPPORT[c.support_status]}
      </p>
      {c.supports.length ? (
        <ul className="supports">
          {c.supports.map((sup) => (
            <li key={sup.id}>
              <blockquote>{sup.quote}</blockquote>
              <p className="hint">
                {sup.kind === "interview" ? (
                  "Your interview answer"
                ) : sup.source_id ? (
                  <Link to={passageLink(sup.source_id, sup.chunk_id)}>
                    {sup.source_title} (@{sup.citation_key}, {sup.locator})
                  </Link>
                ) : (
                  `@${sup.citation_key}`
                )}
                {sup.source_removed ? " · source removed" : ""}
                {!sup.located ? " · passage not located" : ""}
              </p>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="form-row">
        <div className="field">
          <label htmlFor={`${id}-review`}>Your review</label>
          <select
            id={`${id}-review`}
            value={c.review_state}
            disabled={readOnly || actions.patch.isPending}
            onChange={(e) =>
              actions.patch.mutate({ id: c.id, review_state: e.target.value as Claim["review_state"] })
            }
          >
            {Object.entries(REVIEW).map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </div>
      </div>
      {actions.patch.error ? <InlineError error={actions.patch.error} /> : null}
    </li>
  );
}

function AddClaim({ projectId }: { projectId: string }) {
  const id = useId();
  const announce = useAnnounce();
  const actions = useClaimActions(projectId);
  const [text, setText] = useState("");
  const [picked, setPicked] = useState<SearchHit[]>([]);
  return (
    <section className="panel" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>Add a claim</h2>
      <div className="field">
        <label htmlFor={`${id}-text`}>Statement</label>
        <textarea
          id={`${id}-text`}
          rows={3}
          value={text}
          maxLength={2000}
          onChange={(e) => setText(e.target.value)}
        />
      </div>
      {picked.length ? (
        <ul className="supports">
          {picked.map((h) => (
            <li key={h.chunk_id}>
              {h.source_title}, {h.locator}{" "}
              <button
                type="button"
                className="btn btn-small"
                onClick={() => setPicked(picked.filter((x) => x.chunk_id !== h.chunk_id))}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="hint">Search below and pick the passages that support it.</p>
      )}
      <SearchPanel
        scope={{ projectId }}
        label="Find supporting passages"
        pickLabel="Support the claim with this"
        onPick={(h) => setPicked((p) => (p.some((x) => x.chunk_id === h.chunk_id) ? p : [...p, h]))}
      />
      {actions.create.error ? <InlineError error={actions.create.error} /> : null}
      <div className="page-actions">
        <button
          type="button"
          className="btn btn-primary"
          disabled={text.trim().length < 3 || actions.create.isPending}
          onClick={() =>
            actions.create.mutate(
              { text: text.trim(), chunk_ids: picked.map((h) => h.chunk_id) },
              {
                onSuccess: () => {
                  setText("");
                  setPicked([]);
                  announce("Claim added to the ledger");
                },
              },
            )
          }
        >
          Add claim
        </button>
      </div>
    </section>
  );
}
