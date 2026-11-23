import { useId, useState } from "react";
import { useProfileActions, useProfiles, type Profile } from "../../api/knowledge";
import { useAnnounce } from "../../components/Announcer";
import { PageHeader } from "../../components/Misc";
import { EmptyState, ErrorState, InlineError, Loading } from "../../components/States";

const METRICS: [string, string][] = [
  ["sentence_words_mean", "Average sentence length (words)"],
  ["short_sentence_share", "Share of short sentences (8 words or fewer)"],
  ["long_sentence_share", "Share of long sentences (30 words or more)"],
  ["contractions_per_100_words", "Contractions per 100 words"],
  ["first_person_per_100_words", "I / me / my per 100 words"],
  ["second_person_per_100_words", "You / your per 100 words"],
  ["questions_share", "Share of questions"],
  ["em_dashes_per_1000_words", "Em dashes per 1,000 words"],
  ["semicolons_per_1000_words", "Semicolons per 1,000 words"],
  ["vocabulary_variety", "Vocabulary variety (0 to 1)"],
  ["reading_ease_flesch", "Reading ease (Flesch, English)"],
];

/** Author voice: the author's own writing in, an editable style guide out. Used by "Rewrite in my voice". */
export function VoicePage() {
  const id = useId();
  const profiles = useProfiles();
  const actions = useProfileActions();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"author" | "pen_name">("author");
  if (profiles.isError) return <ErrorState error={profiles.error} onRetry={() => void profiles.refetch()} />;
  if (!profiles.data) return <Loading label="Loading voice profiles" />;
  return (
    <>
      <PageHeader
        title="Author voice"
        intro="Describe how you write, from your own writing. The analysis runs on this computer and only describes; your style guide is what AI follows when you ask it to rewrite a passage in your voice, and every rewrite is a suggestion you review."
      />
      <form
        className="form panel"
        aria-labelledby={`${id}-new`}
        onSubmit={(e) => {
          e.preventDefault();
          actions.create.mutate({ name: name.trim(), kind }, { onSuccess: () => setName("") });
        }}
      >
        <h2 id={`${id}-new`}>New voice profile</h2>
        <div className="form-row">
          <div className="field">
            <label htmlFor={`${id}-name`}>Name</label>
            <input id={`${id}-name`} value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor={`${id}-kind`}>This is</label>
            <select id={`${id}-kind`} value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
              <option value="author">My own name</option>
              <option value="pen_name">A pen name</option>
            </select>
          </div>
        </div>
        {actions.create.error ? <InlineError error={actions.create.error} /> : null}
        <div className="page-actions">
          <button type="submit" className="btn btn-primary" disabled={!name.trim()}>
            Create profile
          </button>
        </div>
      </form>
      {profiles.data.length === 0 ? (
        <EmptyState title="No voice profiles yet">
          Create one, then add a few pages of your own writing.
        </EmptyState>
      ) : (
        <div className="stack" style={{ marginTop: "var(--space-5)" }}>
          {profiles.data.map((p) => (
            <ProfilePanel key={`${p.id}-${p.analyzed_at ?? ""}`} profile={p} />
          ))}
        </div>
      )}
    </>
  );
}

function ProfilePanel({ profile: p }: { profile: Profile }) {
  const id = useId();
  const announce = useAnnounce();
  const actions = useProfileActions();
  const [guide, setGuide] = useState(p.style_guide_md);
  const [corrections, setCorrections] = useState(p.corrections.map((c) => ({ ...c, note: c.note ?? "" })));
  const error =
    actions.addSample.error ?? actions.addFile.error ?? actions.patch.error ?? actions.removeSample.error;
  return (
    <section className="panel" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>
        {p.name} <span className="muted">({p.kind === "pen_name" ? "pen name" : "author"})</span>
      </h2>
      {error ? <InlineError error={error} /> : null}

      <h3>Writing samples</h3>
      {p.samples.length ? (
        <ul className="samples">
          {p.samples.map((s) => (
            <li key={s.id}>
              <strong>{s.title}</strong>{" "}
              <span className="muted">
                ({s.word_count} words, {s.rights_basis === "own_writing" ? "your own writing" : "licensed"})
              </span>
              <button
                type="button"
                className="btn btn-small"
                onClick={() => actions.removeSample.mutate({ id: p.id, sampleId: s.id })}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No samples yet.</p>
      )}
      <AddSample profileId={p.id} />

      <h3>What the analysis found</h3>
      {p.analysis_note ? <p className="muted">{p.analysis_note}</p> : null}
      {Object.keys(p.labels).length ? (
        <>
          <p className="hint">
            These are rough, rule-based measures, not judgements. Correct anything below in the style guide.
          </p>
          <p>
            Tone: <strong>{p.labels.formality}</strong>; sentences: <strong>{p.labels.rhythm}</strong>; point
            of view: <strong>{p.labels.point_of_view}</strong>.
          </p>
          <table className="data-table">
            <caption className="visually-hidden">Style measures</caption>
            <tbody>
              {METRICS.filter(([k]) => k in p.metrics).map(([k, label]) => (
                <tr key={k}>
                  <th scope="row">{label}</th>
                  <td>{String(p.metrics[k])}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h4>Sentences typical of you (exact quotes from your samples)</h4>
          <ul className="examples">
            {p.examples.map((e, i) => (
              <li key={i}>
                <blockquote>{e.text}</blockquote> <span className="muted">from {e.sample}</span>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          actions.patch.mutate(
            {
              id: p.id,
              style_guide_md: guide,
              corrections: corrections
                .filter((c) => c.before.trim() && c.after.trim())
                .map((c) => ({
                  before: c.before.trim(),
                  after: c.after.trim(),
                  note: c.note.trim() || null,
                })),
            },
            { onSuccess: () => announce("Style guide saved") },
          );
        }}
      >
        <h3>Style guide</h3>
        <div className="field">
          <label htmlFor={`${id}-guide`}>How I write (you can edit every line)</label>
          <textarea id={`${id}-guide`} rows={10} value={guide} onChange={(e) => setGuide(e.target.value)} />
          <p className="hint">
            {p.guide_edited
              ? "You have edited this guide, so new samples no longer overwrite it."
              : "Drafted from your samples. Once you edit it, new samples will not overwrite it."}
          </p>
        </div>
        <fieldset>
          <legend>Corrections: before and after</legend>
          <p className="hint">Phrases you would never write, and what you would write instead.</p>
          {corrections.map((c, i) => (
            <div className="form-row correction" key={i}>
              <div className="field">
                <label htmlFor={`${id}-b${i}`}>Before</label>
                <input
                  id={`${id}-b${i}`}
                  value={c.before}
                  onChange={(e) =>
                    setCorrections(
                      corrections.map((x, j) => (j === i ? { ...x, before: e.target.value } : x)),
                    )
                  }
                />
              </div>
              <div className="field">
                <label htmlFor={`${id}-a${i}`}>After (how you would write it)</label>
                <input
                  id={`${id}-a${i}`}
                  value={c.after}
                  onChange={(e) =>
                    setCorrections(corrections.map((x, j) => (j === i ? { ...x, after: e.target.value } : x)))
                  }
                />
              </div>
              <button
                type="button"
                className="btn btn-small"
                onClick={() => setCorrections(corrections.filter((_, j) => j !== i))}
              >
                Remove
              </button>
            </div>
          ))}
          <button
            type="button"
            className="btn btn-small"
            onClick={() => setCorrections([...corrections, { before: "", after: "", note: "" }])}
          >
            Add a correction
          </button>
        </fieldset>
        <div className="page-actions">
          <button type="submit" className="btn btn-primary" disabled={actions.patch.isPending}>
            Save style guide
          </button>
        </div>
      </form>
    </section>
  );
}

function AddSample({ profileId }: { profileId: string }) {
  const id = useId();
  const announce = useAnnounce();
  const actions = useProfileActions();
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [rights, setRights] = useState(false);
  const [basis, setBasis] = useState<"own_writing" | "licensed">("own_writing");
  const [inputKey, setInputKey] = useState(0);
  const done = () => {
    setTitle("");
    setText("");
    setFile(null);
    setRights(false);
    setInputKey((k) => k + 1);
    announce("Sample added and analysed");
  };
  return (
    <form
      className="form add-sample"
      aria-labelledby={`${id}-h`}
      onSubmit={(e) => {
        e.preventDefault();
        if (file) actions.addFile.mutate({ id: profileId, file, basis }, { onSuccess: done });
        else
          actions.addSample.mutate(
            {
              id: profileId,
              title: title.trim() || "Pasted sample",
              text,
              rights_confirmed: rights,
              rights_basis: basis,
            },
            { onSuccess: done },
          );
      }}
    >
      <h4 id={`${id}-h`}>Add a sample</h4>
      <div className="form-row">
        <div className="field">
          <label htmlFor={`${id}-file`}>From a file</label>
          <input
            key={inputKey}
            id={`${id}-file`}
            type="file"
            accept=".md,.markdown,.txt,.html,.htm,.docx,.pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </div>
        <div className="field">
          <label htmlFor={`${id}-title`}>Or paste text: title</label>
          <input
            id={`${id}-title`}
            value={title}
            disabled={!!file}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>
      </div>
      <div className="field">
        <label htmlFor={`${id}-text`}>Text</label>
        <textarea
          id={`${id}-text`}
          rows={6}
          value={text}
          disabled={!!file}
          onChange={(e) => setText(e.target.value)}
        />
      </div>
      <fieldset>
        <legend>Whose writing is this?</legend>
        <label className="inline-check">
          <input
            type="radio"
            name={`${id}-basis`}
            checked={basis === "own_writing"}
            onChange={() => setBasis("own_writing")}
          />
          My own writing
        </label>
        <label className="inline-check">
          <input
            type="radio"
            name={`${id}-basis`}
            checked={basis === "licensed"}
            onChange={() => setBasis("licensed")}
          />
          Writing I have the rights to use
        </label>
      </fieldset>
      <label className="inline-check">
        <input type="checkbox" checked={rights} onChange={(e) => setRights(e.target.checked)} />I confirm this
        is my own writing or that I have the rights to use it.
      </label>
      <div className="page-actions">
        <button
          type="submit"
          className="btn"
          disabled={
            !rights || (!file && !text.trim()) || actions.addSample.isPending || actions.addFile.isPending
          }
        >
          Add sample
        </button>
      </div>
    </form>
  );
}
