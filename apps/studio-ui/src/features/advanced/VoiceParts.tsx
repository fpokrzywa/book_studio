import { useId, useState } from "react";
import { Link } from "react-router";
import {
  useProjectSeries,
  useProjectVoice,
  useSetPenName,
  useSetProjectVoice,
  type VoiceRule,
} from "../../api/advanced";
import { useProfiles, type Profile } from "../../api/knowledge";
import { useAnnounce } from "../../components/Announcer";
import { InlineError } from "../../components/States";

/** Pen name and the do/avoid rules every AI request in this voice must follow. */
export function PenNameEditor({ profile: p }: { profile: Profile }) {
  const id = useId();
  const save = useSetPenName();
  const announce = useAnnounce();
  const [pen, setPen] = useState(p.pen_name ?? "");
  const [rules, setRules] = useState<VoiceRule[]>((p.voice_rules as VoiceRule[]) ?? []);
  const set = (i: number, patch: Partial<VoiceRule>) =>
    setRules(rules.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <form
      className="pen-name"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(
          {
            id: p.id,
            body: { pen_name: pen.trim() || null, voice_rules: rules.filter((r) => r.rule.trim()) },
          },
          { onSuccess: () => announce("Pen name and voice rules saved") },
        );
      }}
    >
      <h3>Pen name and voice rules</h3>
      <div className="field">
        <label htmlFor={`${id}-pen`}>Name on the cover</label>
        <input id={`${id}-pen`} value={pen} onChange={(e) => setPen(e.target.value)} maxLength={200} />
      </div>
      <fieldset>
        <legend>Rules AI must follow when writing in this voice</legend>
        {rules.length ? (
          <ol className="voice-rules">
            {rules.map((r, i) => (
              <li key={i} className="form-row compact">
                <div className="field">
                  <label htmlFor={`${id}-k${i}`}>Rule {i + 1}</label>
                  <select
                    id={`${id}-k${i}`}
                    value={r.kind}
                    onChange={(e) => set(i, { kind: e.target.value as VoiceRule["kind"] })}
                  >
                    <option value="do">Do</option>
                    <option value="avoid">Avoid</option>
                  </select>
                </div>
                <div className="field grow">
                  <label htmlFor={`${id}-r${i}`}>What</label>
                  <input
                    id={`${id}-r${i}`}
                    value={r.rule}
                    maxLength={300}
                    onChange={(e) => set(i, { rule: e.target.value })}
                  />
                </div>
                <button
                  type="button"
                  className="btn btn-small"
                  onClick={() => setRules(rules.filter((_, j) => j !== i))}
                >
                  Remove rule {i + 1}
                </button>
              </li>
            ))}
          </ol>
        ) : (
          <p className="muted">No rules yet. Example: Avoid adverbs ending in -ly.</p>
        )}
        <button
          type="button"
          className="btn btn-small"
          onClick={() => setRules([...rules, { kind: "do", rule: "" }])}
        >
          Add a rule
        </button>
      </fieldset>
      <button type="submit" className="btn btn-primary" disabled={save.isPending}>
        Save pen name and rules
      </button>
      {save.error ? <InlineError error={save.error} /> : null}
    </form>
  );
}

/** On the book page: which voice profile (and pen name) AI uses for this book, and the series it belongs to. */
export function ProjectVoicePanel({ projectId }: { projectId: string }) {
  const id = useId();
  const voice = useProjectVoice(projectId);
  const profiles = useProfiles();
  const series = useProjectSeries(projectId);
  const set = useSetProjectVoice(projectId);
  const announce = useAnnounce();
  const v = voice.data;
  return (
    <section className="panel" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>Voice and series</h2>
      {v ? (
        <p>
          Active voice:{" "}
          {v.profile_name ? (
            <>
              <strong>{v.profile_name}</strong>
              {v.pen_name ? (
                <>
                  {" "}
                  writing as <strong>{v.pen_name}</strong>
                </>
              ) : null}
              {v.voice_rules.length ? `, ${v.voice_rules.length} rule(s)` : ""}
            </>
          ) : (
            <strong>none</strong>
          )}
          . <span className="muted">{v.used_for}</span>
        </p>
      ) : null}
      <div className="field">
        <label htmlFor={`${id}-sel`}>Voice profile for this book</label>
        <select
          id={`${id}-sel`}
          value={v?.author_profile_id ?? ""}
          disabled={set.isPending}
          onChange={(e) =>
            set.mutate(e.target.value || null, { onSuccess: () => announce("Voice for this book changed") })
          }
        >
          <option value="">No voice profile</option>
          {(profiles.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
              {p.pen_name ? ` (${p.pen_name})` : ""}
            </option>
          ))}
        </select>
      </div>
      {set.error ? <InlineError error={set.error} /> : null}
      <p>
        {series.data ? (
          <>
            Part of the series <Link to={`/series/${series.data.id}`}>{series.data.title}</Link>.
          </>
        ) : (
          <>
            Not in a series. <Link to="/series">Series</Link>
          </>
        )}
      </p>
    </section>
  );
}
