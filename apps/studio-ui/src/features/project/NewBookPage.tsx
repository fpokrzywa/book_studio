import { useId, useState } from "react";
import { useNavigate } from "react-router";
import { useProfiles, useSharedLibraries } from "../../api/knowledge";
import { BOOK_KIND_OF, useCreateBook, type BriefIn } from "../../api/planning";
import { useAnnounce } from "../../components/Announcer";
import { PageHeader } from "../../components/Misc";
import { initialValues, ProjectForm } from "./ProjectForm";

interface PlanValues {
  genre: string;
  purpose: string;
  promise: string;
  tone: string;
  author_profile_id: string;
  desired_chapters: string;
  approval_preference: BriefIn["approval_preference"];
  budget_cap: string;
  budget_currency: string;
  max_chapters_per_run: string;
  shared_library_ids: string[];
}

const EMPTY: PlanValues = {
  genre: "",
  purpose: "",
  promise: "",
  tone: "",
  author_profile_id: "",
  desired_chapters: "",
  approval_preference: "review_each_chapter",
  budget_cap: "",
  budget_currency: "USD",
  max_chapters_per_run: "10",
  shared_library_ids: [],
};

/** The New Book wizard: the book itself (step 1), then its reader, shape, sources and approvals. */
export function NewBookPage() {
  const create = useCreateBook();
  const navigate = useNavigate();
  const announce = useAnnounce();
  const [plan, setPlan] = useState<PlanValues>(EMPTY);

  return (
    <>
      <PageHeader
        title="Start a new book"
        intro="Only the title is required. Everything here can be changed later in the book's plan, and the book stays on this computer."
      />
      <ProjectForm
        initial={initialValues()}
        submitLabel="Create book"
        busy={create.isPending}
        serverError={create.error}
        extra={<PlanFields values={plan} onChange={setPlan} />}
        onSubmit={(project) =>
          create.mutate(
            {
              project,
              brief: {
                kind: BOOK_KIND_OF[project.project_type] ?? "nonfiction",
                genre: plan.genre.trim() || null,
                purpose: plan.purpose.trim() || null,
                promise: plan.promise.trim() || null,
                tone: plan.tone.trim() || null,
                author_profile_id: plan.author_profile_id || null,
                desired_chapters: plan.desired_chapters ? Number(plan.desired_chapters) : null,
                approval_preference: plan.approval_preference,
                budget_cap: plan.budget_cap.trim() || null,
                budget_currency: plan.budget_cap.trim() ? plan.budget_currency : null,
                max_chapters_per_run: Number(plan.max_chapters_per_run) || 10,
                words_per_hour: 500,
                exclusions: [],
                assumptions: [],
              },
              shared_library_ids: plan.shared_library_ids,
            },
            {
              onSuccess: ({ project: p }) => {
                announce(`Created “${p.title}”`);
                navigate(`/projects/${p.id}`);
              },
            },
          )
        }
        onCancel={() => navigate("/")}
      />
    </>
  );
}

function PlanFields({ values, onChange }: { values: PlanValues; onChange: (v: PlanValues) => void }) {
  const id = useId();
  const profiles = useProfiles();
  const libraries = useSharedLibraries();
  const set = (k: keyof PlanValues) => (e: { target: { value: string } }) =>
    onChange({ ...values, [k]: e.target.value });
  return (
    <div className="wizard-steps">
      <fieldset className="wizard-step">
        <legend>2. Reader and promise (optional)</legend>
        <div className="form-row">
          <div className="field">
            <label htmlFor={`${id}-genre`}>Genre</label>
            <input id={`${id}-genre`} value={values.genre} maxLength={300} onChange={set("genre")} />
          </div>
          <div className="field">
            <label htmlFor={`${id}-tone`}>Tone</label>
            <input
              id={`${id}-tone`}
              value={values.tone}
              maxLength={300}
              placeholder="For example: plain and encouraging"
              onChange={set("tone")}
            />
          </div>
        </div>
        <div className="field">
          <label htmlFor={`${id}-purpose`}>Purpose</label>
          <textarea
            id={`${id}-purpose`}
            rows={2}
            value={values.purpose}
            maxLength={2000}
            onChange={set("purpose")}
          />
        </div>
        <div className="field">
          <label htmlFor={`${id}-promise`}>Main promise to the reader</label>
          <textarea
            id={`${id}-promise`}
            rows={2}
            value={values.promise}
            maxLength={2000}
            onChange={set("promise")}
          />
          <p className="hint">What will the reader have, know or feel by the end?</p>
        </div>
        <div className="field">
          <label htmlFor={`${id}-profile`}>Author voice</label>
          <select id={`${id}-profile`} value={values.author_profile_id} onChange={set("author_profile_id")}>
            <option value="">None yet</option>
            {(profiles.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
      </fieldset>
      <fieldset className="wizard-step">
        <legend>3. Shape and sources (optional)</legend>
        <div className="form-row">
          <div className="field">
            <label htmlFor={`${id}-chapters`}>How many chapters?</label>
            <input
              id={`${id}-chapters`}
              type="number"
              min={1}
              max={200}
              inputMode="numeric"
              value={values.desired_chapters}
              onChange={set("desired_chapters")}
            />
          </div>
        </div>
        {(libraries.data ?? []).length > 0 ? (
          <fieldset>
            <legend>Use these shared libraries</legend>
            {(libraries.data ?? []).map((lib) => (
              <label key={lib.id} className="inline-check">
                <input
                  type="checkbox"
                  checked={values.shared_library_ids.includes(lib.id)}
                  onChange={(e) =>
                    onChange({
                      ...values,
                      shared_library_ids: e.target.checked
                        ? [...values.shared_library_ids, lib.id]
                        : values.shared_library_ids.filter((x) => x !== lib.id),
                    })
                  }
                />
                {lib.name}
              </label>
            ))}
          </fieldset>
        ) : (
          <p className="hint">You can add source files to the book after creating it (Sources).</p>
        )}
      </fieldset>
      <fieldset className="wizard-step">
        <legend>4. Approvals and budget (optional)</legend>
        <fieldset>
          <legend>How AI drafts reach your manuscript</legend>
          <label className="inline-check">
            <input
              type="radio"
              name={`${id}-approval`}
              checked={values.approval_preference === "review_each_chapter"}
              onChange={() => onChange({ ...values, approval_preference: "review_each_chapter" })}
            />
            Approve the outline, then ask for chapters one at a time
          </label>
          <label className="inline-check">
            <input
              type="radio"
              name={`${id}-approval`}
              checked={values.approval_preference === "review_outline_then_batch"}
              onChange={() => onChange({ ...values, approval_preference: "review_outline_then_batch" })}
            />
            Approve the outline, then draft many chapters in one run
          </label>
          <p className="hint">
            Either way, every AI chapter is a suggestion you review before it becomes text.
          </p>
        </fieldset>
        <div className="form-row">
          <div className="field">
            <label htmlFor={`${id}-cap`}>Budget cap per run (optional)</label>
            <input
              id={`${id}-cap`}
              inputMode="decimal"
              value={values.budget_cap}
              placeholder="No cap"
              onChange={set("budget_cap")}
            />
            <p className="hint">A run that could cost more is refused; local models cost nothing.</p>
          </div>
          <div className="field">
            <label htmlFor={`${id}-cur`}>Currency</label>
            <input
              id={`${id}-cur`}
              value={values.budget_currency}
              maxLength={3}
              onChange={set("budget_currency")}
            />
          </div>
          <div className="field">
            <label htmlFor={`${id}-limit`}>Most chapters per run</label>
            <input
              id={`${id}-limit`}
              type="number"
              min={1}
              max={200}
              value={values.max_chapters_per_run}
              onChange={set("max_chapters_per_run")}
            />
          </div>
        </div>
      </fieldset>
    </div>
  );
}
