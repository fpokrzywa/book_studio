import { useId, useState, type FormEvent } from "react";
import type { Project, ProjectCreate, ProjectType, PublicationFormat } from "../../api/client";
import { ApiError } from "../../api/client";
import { FORMATS, PROJECT_TYPES } from "../../lib/format";

export interface ProjectFormValues {
  title: string;
  subtitle: string;
  author_name: string;
  description: string;
  project_type: ProjectType;
  language: string;
  audience: string;
  target_word_count: string;
  publication_formats: PublicationFormat[];
}

export function initialValues(p?: Project): ProjectFormValues {
  return {
    title: p?.title ?? "",
    subtitle: p?.subtitle ?? "",
    author_name: p?.author_name ?? "",
    description: p?.description ?? "",
    project_type: p?.project_type ?? "nonfiction",
    language: p?.language ?? "en",
    audience: p?.audience ?? "",
    target_word_count: p?.target_word_count != null ? String(p.target_word_count) : "",
    publication_formats: p?.publication_formats ?? ["ebook"],
  };
}

type Errors = Partial<Record<keyof ProjectFormValues, string>>;

const LANG = /^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$/;

export function validate(v: ProjectFormValues): Errors {
  const e: Errors = {};
  if (!v.title.trim()) e.title = "Give the book a working title. You can change it later.";
  else if (v.title.trim().length > 300) e.title = "Keep the title under 300 characters.";
  if (!LANG.test(v.language.trim())) e.language = "Use a language tag such as en, en-GB or fr.";
  if (v.target_word_count.trim()) {
    const num = Number(v.target_word_count);
    if (!Number.isInteger(num) || num < 0)
      e.target_word_count = "Enter a whole number of words, or leave it empty.";
    else if (num > 5_000_000) e.target_word_count = "That is more than 5 million words. Check the number.";
  }
  return e;
}

export function toPayload(v: ProjectFormValues): ProjectCreate {
  const opt = (s: string) => (s.trim() ? s.trim() : null);
  return {
    title: v.title.trim(),
    subtitle: opt(v.subtitle),
    author_name: opt(v.author_name),
    description: v.description.trim() ? v.description.trim() : null,
    project_type: v.project_type,
    language: v.language.trim(),
    audience: opt(v.audience),
    target_word_count: v.target_word_count.trim() ? Number(v.target_word_count) : null,
    publication_formats: v.publication_formats,
  };
}

interface Props {
  initial: ProjectFormValues;
  submitLabel: string;
  busy?: boolean;
  serverError?: unknown;
  onSubmit: (payload: ProjectCreate) => void;
  onCancel?: () => void;
}

export function ProjectForm({ initial, submitLabel, busy, serverError, onSubmit, onCancel }: Props) {
  const [values, setValues] = useState(initial);
  const [errors, setErrors] = useState<Errors>({});
  const id = useId();

  const set = <K extends keyof ProjectFormValues>(key: K, value: ProjectFormValues[K]) =>
    setValues((v) => ({ ...v, [key]: value }));

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const found = validate(values);
    setErrors(found);
    if (Object.keys(found).length > 0) {
      const first = Object.keys(found)[0];
      document.getElementById(`${id}-${first}`)?.focus();
      return;
    }
    onSubmit(toPayload(values));
  }

  const fieldProps = (key: keyof ProjectFormValues) => ({
    id: `${id}-${key}`,
    "aria-invalid": errors[key] ? true : undefined,
    "aria-describedby": errors[key] ? `${id}-${key}-error` : undefined,
  });
  const errorFor = (key: keyof ProjectFormValues) =>
    errors[key] ? (
      <span className="error" id={`${id}-${key}-error`}>
        {errors[key]}
      </span>
    ) : null;

  const server = serverError instanceof ApiError ? serverError.problem : null;

  return (
    <form className="form" onSubmit={handleSubmit} noValidate>
      {serverError ? (
        <div className="inline-error" role="alert">
          <strong>{server?.title ?? "The book could not be saved."}</strong> {server?.detail}
        </div>
      ) : null}
      <div className="field">
        <label htmlFor={`${id}-title`}>Title</label>
        <input
          type="text"
          {...fieldProps("title")}
          value={values.title}
          onChange={(e) => set("title", e.target.value)}
          required
          maxLength={300}
        />
        {errorFor("title")}
      </div>
      <div className="form-row">
        <div className="field">
          <label htmlFor={`${id}-subtitle`}>Subtitle</label>
          <input
            type="text"
            {...fieldProps("subtitle")}
            value={values.subtitle}
            onChange={(e) => set("subtitle", e.target.value)}
            maxLength={300}
          />
        </div>
        <div className="field">
          <label htmlFor={`${id}-author_name`}>Author or pen name</label>
          <input
            type="text"
            {...fieldProps("author_name")}
            value={values.author_name}
            onChange={(e) => set("author_name", e.target.value)}
            maxLength={200}
          />
        </div>
      </div>
      <div className="field">
        <label htmlFor={`${id}-description`}>Short description</label>
        <textarea
          {...fieldProps("description")}
          rows={3}
          value={values.description}
          onChange={(e) => set("description", e.target.value)}
          maxLength={4000}
        />
      </div>
      <div className="form-row">
        <div className="field">
          <label htmlFor={`${id}-project_type`}>Kind of book</label>
          <select
            {...fieldProps("project_type")}
            value={values.project_type}
            onChange={(e) => set("project_type", e.target.value as ProjectType)}
          >
            {PROJECT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor={`${id}-language`}>Language</label>
          <input
            type="text"
            {...fieldProps("language")}
            aria-describedby={errors.language ? `${id}-language-error` : `${id}-language-hint`}
            value={values.language}
            onChange={(e) => set("language", e.target.value)}
            maxLength={35}
          />
          <span className="hint" id={`${id}-language-hint`}>
            Language tag, for example en, en-GB, es or de.
          </span>
          {errorFor("language")}
        </div>
      </div>
      <div className="field">
        <label htmlFor={`${id}-audience`}>Intended audience</label>
        <input
          type="text"
          {...fieldProps("audience")}
          value={values.audience}
          onChange={(e) => set("audience", e.target.value)}
          maxLength={500}
        />
      </div>
      <div className="form-row">
        <div className="field">
          <label htmlFor={`${id}-target_word_count`}>Target length in words</label>
          <input
            type="number"
            inputMode="numeric"
            min={0}
            step={1000}
            {...fieldProps("target_word_count")}
            value={values.target_word_count}
            onChange={(e) => set("target_word_count", e.target.value)}
          />
          {errorFor("target_word_count")}
        </div>
        <fieldset className="field">
          <legend>Publication formats</legend>
          <div className="checks">
            {FORMATS.map((f) => (
              <label key={f.value}>
                <input
                  type="checkbox"
                  checked={values.publication_formats.includes(f.value)}
                  onChange={(e) =>
                    set(
                      "publication_formats",
                      e.target.checked
                        ? FORMATS.map((x) => x.value).filter(
                            (x) => x === f.value || values.publication_formats.includes(x),
                          )
                        : values.publication_formats.filter((x) => x !== f.value),
                    )
                  }
                />
                {f.label}
              </label>
            ))}
          </div>
        </fieldset>
      </div>
      <div className="page-actions">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Saving…" : submitLabel}
        </button>
        {onCancel ? (
          <button type="button" className="btn" onClick={onCancel}>
            Cancel
          </button>
        ) : null}
      </div>
    </form>
  );
}
