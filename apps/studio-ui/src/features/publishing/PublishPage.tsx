import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router";
import { useProject, useProjects } from "../../api/hooks";
import {
  KIND_LABEL,
  STATUS_LABEL,
  fileUrl,
  packageFileUrl,
  pdfPageUrl,
  reportUrl,
  useAssets,
  useCoverSpec,
  useHtmlPreview,
  usePublications,
  usePublishActions,
  usePublishingProfile,
  useSaveProfile,
  type BuildFormat,
  type PackageResult,
  type Profile,
  type ProfileIn,
  type Publication,
} from "../../api/publishing";
import { useAnnounce } from "../../components/Announcer";
import { PageHeader } from "../../components/Misc";
import { ErrorState, InlineError, Loading } from "../../components/States";
import { relativeTime } from "../../lib/format";

const TABS = [
  ["setup", "Book setup"],
  ["metadata", "Store details"],
  ["cover", "Cover"],
  ["build", "Build and preview"],
  ["package", "Publish package"],
] as const;
type Tab = (typeof TABS)[number][0];

/** The Publishing menu: pick a book. */
export function PublishingHome() {
  const projects = useProjects({ status: "active" });
  return (
    <>
      <PageHeader
        title="Publishing"
        intro="Build EPUB, Word, print PDF and covers, check them against Amazon KDP's published specifications, and get a folder ready for you to upload by hand. Nothing is published for you."
      />
      {projects.isPending ? (
        <Loading label="Loading books" />
      ) : (
        <ul className="link-list">
          {(projects.data?.items ?? []).map((p) => (
            <li key={p.id}>
              <Link to={`/projects/${p.id}/publish`}>{p.title}</Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function toIn(p: Profile): ProfileIn {
  return {
    template: p.template,
    trim: p.trim,
    ink_paper: p.ink_paper,
    matter: p.matter as ProfileIn["matter"],
    copyright: p.copyright as ProfileIn["copyright"],
    metadata: p.metadata as ProfileIn["metadata"],
    cover: p.cover as ProfileIn["cover"],
    index_terms: p.index_terms,
  };
}

export function PublishPage() {
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find(([t]) => t === params.get("tab"))?.[0] ?? "setup") as Tab;
  const project = useProject(projectId);
  const profile = usePublishingProfile(projectId);
  if (profile.isError) return <ErrorState error={profile.error} onRetry={() => void profile.refetch()} />;
  if (!project.data || !profile.data) return <Loading label="Loading publishing" />;
  const rules = profile.data.rules as { ruleset: string; checked_on: string };
  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to={`/projects/${projectId}`}>{project.data.title}</Link>
      </nav>
      <PageHeader
        title="Publish"
        intro="Build and check the files for Kindle eBook and paperback. You upload them to KDP yourself; passing these checks does not mean KDP will accept the book."
      />
      <p className="hint">
        KDP rules: <strong>{rules.ruleset}</strong>, checked against KDP's help pages on {rules.checked_on}.
      </p>
      <nav className="plan-tabs" aria-label="Publishing steps">
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
      {tab === "setup" ? <SetupTab projectId={projectId} profile={profile.data} /> : null}
      {tab === "metadata" ? <MetadataTab projectId={projectId} profile={profile.data} /> : null}
      {tab === "cover" ? <CoverTab projectId={projectId} profile={profile.data} /> : null}
      {tab === "build" ? <BuildTab projectId={projectId} /> : null}
      {tab === "package" ? <PackageTab projectId={projectId} profile={profile.data} /> : null}
    </>
  );
}

function SaveBar({ projectId, draft }: { projectId: string; draft: ProfileIn }) {
  const save = useSaveProfile(projectId);
  const announce = useAnnounce();
  return (
    <div className="page-actions">
      <button
        type="button"
        className="btn btn-primary"
        disabled={save.isPending}
        onClick={() => save.mutate(draft, { onSuccess: () => announce("Publishing settings saved") })}
      >
        Save
      </button>
      {save.error ? <InlineError error={save.error} /> : null}
    </div>
  );
}

// ---------- setup ----------

function SetupTab({ projectId, profile }: { projectId: string; profile: Profile }) {
  const id = useId();
  const [d, setD] = useState<ProfileIn>(() => toIn(profile));
  const opts = profile.options as {
    templates: Record<string, { label: string; trim: string }>;
    trims: Record<string, { width_in: string; height_in: string; pages: Record<string, number[] | null> }>;
    ink_paper: Record<string, string>;
    matter_kinds: Record<string, { position: string; title: string; generated: boolean }>;
  };
  const range = opts.trims[d.trim]?.pages[d.ink_paper];
  const matter = d.matter;
  const setMatter = (i: number, patch: Partial<(typeof matter)[number]>) =>
    setD({ ...d, matter: matter.map((m, j) => (j === i ? { ...m, ...patch } : m)) });
  return (
    <div className="stack">
      <section className="panel" aria-labelledby={`${id}-int`}>
        <h2 id={`${id}-int`}>Interior</h2>
        <div className="form-row">
          <div className="field">
            <label htmlFor={`${id}-tpl`}>Interior template</label>
            <select
              id={`${id}-tpl`}
              value={d.template}
              onChange={(e) => {
                const t = e.target.value as ProfileIn["template"];
                setD({ ...d, template: t, trim: opts.templates[t]?.trim ?? d.trim });
              }}
            >
              {Object.entries(opts.templates).map(([k, v]) => (
                <option key={k} value={k}>
                  {v.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor={`${id}-trim`}>Trim size (inches)</label>
            <select id={`${id}-trim`} value={d.trim} onChange={(e) => setD({ ...d, trim: e.target.value })}>
              {Object.entries(opts.trims).map(([k, v]) => (
                <option key={k} value={k}>
                  {v.width_in} × {v.height_in}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor={`${id}-ink`}>Ink and paper</label>
            <select
              id={`${id}-ink`}
              value={d.ink_paper}
              onChange={(e) => setD({ ...d, ink_paper: e.target.value as ProfileIn["ink_paper"] })}
            >
              {Object.entries(opts.ink_paper).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </div>
        </div>
        <p className="hint" aria-live="polite">
          {range
            ? `KDP prints this trim with this ink and paper for ${range[0]}–${range[1]} pages.`
            : "KDP does not offer this trim with this ink and paper."}{" "}
          Margins, the gutter for the final page count, running heads, page numbers and caption numbers come
          from the template.
        </p>
      </section>
      <section className="panel" aria-labelledby={`${id}-matter`}>
        <h2 id={`${id}-matter`}>Front and back matter</h2>
        <p className="hint">
          Generated items (title page, contents, bibliography, index, notes) are built from your book. Text
          items use only what you write; an item turned on with no text is left out and reported.
        </p>
        <ul className="matter-list">
          {matter.map((m, i) => {
            const k = opts.matter_kinds[m.kind];
            return (
              <li key={m.kind}>
                <label className="inline-check">
                  <input
                    type="checkbox"
                    checked={!!m.enabled}
                    onChange={(e) => setMatter(i, { enabled: e.target.checked })}
                  />
                  {k?.title ?? m.kind}{" "}
                  <span className="muted">
                    ({k?.position === "front" ? "front" : "back"}
                    {k?.generated ? ", generated" : ""})
                  </span>
                </label>
                {m.enabled && !k?.generated ? (
                  <div className="field">
                    <label htmlFor={`${id}-m-${m.kind}`}>Text for {k?.title ?? m.kind} (Markdown)</label>
                    <textarea
                      id={`${id}-m-${m.kind}`}
                      rows={4}
                      value={m.body_md ?? ""}
                      onChange={(e) => setMatter(i, { body_md: e.target.value })}
                      placeholder={m.kind === "glossary" ? "- **Term**: definition (one per line)" : ""}
                    />
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      </section>
      <section className="panel" aria-labelledby={`${id}-copy`}>
        <h2 id={`${id}-copy`}>Copyright page</h2>
        <p className="hint">
          PBS writes no legal text and never makes up an ISBN. Enter your own notice, or leave the page off.
        </p>
        <div className="form-row">
          {(["holder", "year", "edition", "isbn"] as const).map((f) => (
            <div className="field" key={f}>
              <label htmlFor={`${id}-c-${f}`}>
                {
                  {
                    holder: "Copyright holder",
                    year: "Year",
                    edition: "Edition",
                    isbn: "ISBN (if you have one)",
                  }[f]
                }
              </label>
              <input
                id={`${id}-c-${f}`}
                value={(d.copyright?.[f] as string) ?? ""}
                onChange={(e) =>
                  setD({ ...d, copyright: { ...d.copyright, [f]: e.target.value } as ProfileIn["copyright"] })
                }
              />
            </div>
          ))}
        </div>
        <div className="field">
          <label htmlFor={`${id}-c-notice`}>Your copyright notice (optional)</label>
          <textarea
            id={`${id}-c-notice`}
            rows={3}
            value={d.copyright?.notice_md ?? ""}
            onChange={(e) =>
              setD({
                ...d,
                copyright: { ...d.copyright, notice_md: e.target.value } as ProfileIn["copyright"],
              })
            }
          />
        </div>
      </section>
      <section className="panel" aria-labelledby={`${id}-idx`}>
        <h2 id={`${id}-idx`}>Index terms</h2>
        <div className="field">
          <label htmlFor={`${id}-terms`}>One term per line</label>
          <textarea
            id={`${id}-terms`}
            rows={4}
            value={(d.index_terms ?? []).join("\n")}
            onChange={(e) => setD({ ...d, index_terms: e.target.value.split("\n").filter((x) => x.trim()) })}
          />
          <p className="hint">The print PDF lists page numbers; EPUB, Word and HTML link to the chapters.</p>
        </div>
      </section>
      <SaveBar projectId={projectId} draft={d} />
    </div>
  );
}

// ---------- store details ----------

function MetadataTab({ projectId, profile }: { projectId: string; profile: Profile }) {
  const id = useId();
  const [d, setD] = useState<ProfileIn>(() => toIn(profile));
  const m = d.metadata ?? ({} as NonNullable<ProfileIn["metadata"]>);
  const set = (patch: Partial<NonNullable<ProfileIn["metadata"]>>) =>
    setD({ ...d, metadata: { ...m, ...patch } });
  const kws = [...(m.keywords ?? []), "", "", "", "", "", "", ""].slice(0, 7);
  const cats = [...(m.categories ?? []).map((c) => c.text), "", "", ""].slice(0, 3);
  const ai = m.ai_disclosure ?? { text: "", images: "", translation: "" };
  const rules = profile.rules as { ai_definitions: Record<string, string> };
  const evidence = profile.ai_evidence as { ai_revisions?: number };
  return (
    <div className="stack">
      <section className="panel" aria-labelledby={`${id}-d`}>
        <h2 id={`${id}-d`}>Description and keywords</h2>
        <div className="field">
          <label htmlFor={`${id}-desc`}>Book description</label>
          <textarea
            id={`${id}-desc`}
            rows={6}
            maxLength={4000}
            value={m.description ?? ""}
            onChange={(e) => set({ description: e.target.value })}
          />
          <p className="hint">
            No web addresses, emails, prices, reviews or claims like “bestseller”: KDP does not allow them.
          </p>
        </div>
        <fieldset>
          <legend>Keywords (up to seven)</legend>
          <div className="keyword-grid">
            {kws.map((k, i) => (
              <div className="field" key={i}>
                <label htmlFor={`${id}-kw-${i}`}>Keyword {i + 1}</label>
                <input
                  id={`${id}-kw-${i}`}
                  maxLength={100}
                  value={k}
                  onChange={(e) =>
                    set({
                      keywords: kws
                        .map((x, j) => (j === i ? e.target.value : x))
                        .filter((x, j, a) => x || a.slice(j).some(Boolean)),
                    })
                  }
                />
              </div>
            ))}
          </div>
        </fieldset>
        <fieldset>
          <legend>Category ideas (unverified)</legend>
          <p className="hint">
            Suggestions only. Choose real categories in KDP's category picker, which lists what exists today.
          </p>
          {cats.map((c, i) => (
            <div className="field" key={i}>
              <label htmlFor={`${id}-cat-${i}`}>Category idea {i + 1}</label>
              <input
                id={`${id}-cat-${i}`}
                maxLength={300}
                value={c}
                onChange={(e) =>
                  set({
                    categories: cats
                      .map((x, j) => (j === i ? e.target.value : x))
                      .filter(Boolean)
                      .map((text) => ({ text, verified: false })),
                  })
                }
              />
            </div>
          ))}
        </fieldset>
        <div className="form-row">
          <div className="field">
            <label htmlFor={`${id}-amin`}>Youngest reader (age, optional)</label>
            <input
              id={`${id}-amin`}
              type="number"
              min={0}
              max={18}
              value={m.age_min ?? ""}
              onChange={(e) => set({ age_min: e.target.value === "" ? null : Number(e.target.value) })}
            />
          </div>
          <div className="field">
            <label htmlFor={`${id}-amax`}>Oldest reader (age, optional)</label>
            <input
              id={`${id}-amax`}
              type="number"
              min={0}
              max={18}
              value={m.age_max ?? ""}
              onChange={(e) => set({ age_max: e.target.value === "" ? null : Number(e.target.value) })}
            />
          </div>
        </div>
      </section>
      <section className="panel" aria-labelledby={`${id}-ai`}>
        <h2 id={`${id}-ai`}>AI disclosure checklist</h2>
        <p className="hint">{rules.ai_definitions.ai_generated}</p>
        <p className="hint">{rules.ai_definitions.ai_assisted}</p>
        {evidence.ai_revisions ? (
          <p role="note">
            PBS recorded {evidence.ai_revisions} chapter revision(s) made from AI suggestions you accepted.
          </p>
        ) : null}
        {(["text", "images", "translation"] as const).map((k) => (
          <fieldset className="segmented" key={k}>
            <legend>
              {{ text: "Text", images: "Images (including the cover)", translation: "Translations" }[k]}
            </legend>
            {(
              [
                ["none", "No AI used"],
                ["assisted", "AI-assisted only"],
                ["generated", "Contains AI-generated content"],
              ] as const
            ).map(([v, label]) => (
              <label key={v}>
                <input
                  type="radio"
                  name={`${id}-ai-${k}`}
                  checked={ai[k] === v}
                  onChange={() => set({ ai_disclosure: { ...ai, [k]: v } })}
                />
                {label}
              </label>
            ))}
          </fieldset>
        ))}
      </section>
      <SaveBar projectId={projectId} draft={d} />
    </div>
  );
}

// ---------- cover ----------

type Layer = NonNullable<NonNullable<ProfileIn["cover"]>["layers"]>[number];

function CoverTab({ projectId, profile }: { projectId: string; profile: Profile }) {
  const id = useId();
  const [d, setD] = useState<ProfileIn>(() => toIn(profile));
  const spec = useCoverSpec(projectId);
  const assets = useAssets(projectId);
  const pubs = usePublications(projectId);
  const actions = usePublishActions(projectId);
  const c = d.cover ?? ({} as NonNullable<ProfileIn["cover"]>);
  const set = (patch: Partial<NonNullable<ProfileIn["cover"]>>) => setD({ ...d, cover: { ...c, ...patch } });
  const layers = c.layers ?? [];
  const setLayer = (i: number, patch: Partial<Layer>) =>
    set({ layers: layers.map((l, j) => (j === i ? { ...l, ...patch } : l)) });
  const latest = (kind: string) => (pubs.data ?? []).find((p) => p.kind === kind && !p.package_id);
  const tools = profile.tools as { image_generation: string };
  const s = spec.data;
  const sp = s?.spec as Record<string, string | boolean> | null | undefined;
  return (
    <div className="stack">
      <section className="panel" aria-labelledby={`${id}-size`}>
        <h2 id={`${id}-size`}>Size from the final page count</h2>
        {s ? <p aria-live="polite">{s.message}</p> : <Loading label="Calculating" />}
        {sp ? (
          <dl className="facts-grid">
            <dt>Pages (from the print PDF)</dt>
            <dd>{String(sp.page_count)}</dd>
            <dt>Spine</dt>
            <dd>{String(sp.spine_width_in)} in</dd>
            <dt>Full cover</dt>
            <dd>
              {String(sp.cover_width_in)} × {String(sp.cover_height_in)} in (with {String(sp.bleed_in)} in
              bleed)
            </dd>
            <dt>Spine text</dt>
            <dd>{sp.spine_text_allowed ? "Allowed" : "Not allowed below 79 pages"}</dd>
          </dl>
        ) : null}
        {s?.latest_cover?.stale ? (
          <p className="inline-error" role="alert">
            The last cover was built for {String(s.latest_cover.page_count)} pages. Build it again.
          </p>
        ) : null}
        <p className="hint">
          Width = bleed + back + spine + front + bleed. The barcode area (2 × 1.2 in) is kept clear and white.
          KDP does not publish where it puts the barcode, so compare with KDP's cover template before you
          upload.
        </p>
      </section>
      <section className="panel" aria-labelledby={`${id}-art`}>
        <h2 id={`${id}-art`}>Artwork and colours</h2>
        <p className="hint">
          Image generation: {tools.image_generation} Lettering is always typography, never part of a picture.
        </p>
        <div className="form-row">
          <div className="field">
            <label htmlFor={`${id}-bg`}>Background colour</label>
            <input
              id={`${id}-bg`}
              type="color"
              value={c.background ?? "#1f3a5f"}
              onChange={(e) => set({ background: e.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor={`${id}-fg`}>Text colour</label>
            <input
              id={`${id}-fg`}
              type="color"
              value={c.text_color ?? "#ffffff"}
              onChange={(e) => set({ text_color: e.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor={`${id}-artsel`}>Artwork (an image in this book)</label>
            <select
              id={`${id}-artsel`}
              value={c.artwork_asset ?? ""}
              onChange={(e) => set({ artwork_asset: e.target.value || null })}
            >
              <option value="">None</option>
              {(assets.data ?? []).map((a) => (
                <option key={a.short_hash} value={a.short_hash}>
                  {a.original_name ?? a.short_hash} ({a.width_px}×{a.height_px} px)
                </option>
              ))}
            </select>
          </div>
        </div>
        {c.artwork_asset ? (
          <fieldset>
            <legend>Rights to the artwork</legend>
            <div className="form-row">
              <div className="field">
                <label htmlFor={`${id}-src`}>Where it comes from</label>
                <input
                  id={`${id}-src`}
                  value={c.artwork_license?.source ?? ""}
                  onChange={(e) =>
                    set({ artwork_license: { ...c.artwork_license!, source: e.target.value } })
                  }
                />
              </div>
              <div className="field">
                <label htmlFor={`${id}-lic`}>License</label>
                <input
                  id={`${id}-lic`}
                  value={c.artwork_license?.license ?? ""}
                  onChange={(e) =>
                    set({ artwork_license: { ...c.artwork_license!, license: e.target.value } })
                  }
                />
              </div>
            </div>
            <label className="inline-check">
              <input
                type="checkbox"
                checked={!!c.artwork_license?.confirmed}
                onChange={(e) =>
                  set({
                    artwork_license: {
                      source: "",
                      license: "",
                      ...c.artwork_license,
                      confirmed: e.target.checked,
                    },
                  })
                }
              />
              I have the right to use this artwork on a book cover I sell
            </label>
          </fieldset>
        ) : null}
      </section>
      <section className="panel" aria-labelledby={`${id}-type`}>
        <h2 id={`${id}-type`}>Typography</h2>
        <ul className="layer-list">
          {layers.map((l, i) => (
            <li key={l.role}>
              <fieldset>
                <legend>
                  {
                    {
                      title: "Title",
                      subtitle: "Subtitle",
                      author: "Author",
                      spine: "Spine",
                      back_text: "Back cover text",
                    }[l.role]
                  }
                </legend>
                <div className="field">
                  <label htmlFor={`${id}-l${i}-t`}>Text</label>
                  {l.role === "back_text" ? (
                    <textarea
                      id={`${id}-l${i}-t`}
                      rows={4}
                      value={l.text ?? ""}
                      onChange={(e) => setLayer(i, { text: e.target.value })}
                    />
                  ) : (
                    <input
                      id={`${id}-l${i}-t`}
                      value={l.text ?? ""}
                      onChange={(e) => setLayer(i, { text: e.target.value })}
                    />
                  )}
                </div>
                <div className="form-row compact">
                  <div className="field">
                    <label htmlFor={`${id}-l${i}-s`}>Size (pt)</label>
                    <input
                      id={`${id}-l${i}-s`}
                      type="number"
                      min={7}
                      max={120}
                      value={l.size_pt ?? 12}
                      onChange={(e) => setLayer(i, { size_pt: Number(e.target.value) })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`${id}-l${i}-y`}>Position from top (0–1)</label>
                    <input
                      id={`${id}-l${i}-y`}
                      type="number"
                      min={0}
                      max={1}
                      step={0.02}
                      value={l.y ?? 0.2}
                      onChange={(e) => setLayer(i, { y: Number(e.target.value) })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`${id}-l${i}-f`}>Font</label>
                    <select
                      id={`${id}-l${i}-f`}
                      value={l.font ?? "Libertinus Serif"}
                      onChange={(e) => setLayer(i, { font: e.target.value as Layer["font"] })}
                    >
                      {["Libertinus Serif", "New Computer Modern", "DejaVu Sans Mono"].map((f) => (
                        <option key={f}>{f}</option>
                      ))}
                    </select>
                  </div>
                </div>
              </fieldset>
            </li>
          ))}
        </ul>
      </section>
      <SaveBar projectId={projectId} draft={d} />
      <section className="panel" aria-labelledby={`${id}-build`}>
        <h2 id={`${id}-build`}>Build the covers</h2>
        <button
          type="button"
          className="btn btn-primary"
          disabled={actions.covers.isPending || !sp}
          onClick={() => actions.covers.mutate()}
        >
          Build covers from the latest print PDF
        </button>
        {actions.covers.error ? <InlineError error={actions.covers.error} /> : null}
        <ul className="link-list">
          {(["cover_print", "cover_proof", "cover_ebook"] as const).map((k) => {
            const p = latest(k);
            return p ? (
              <li key={k}>
                <a href={fileUrl(projectId, p.id, true)} target="_blank" rel="noreferrer">
                  {KIND_LABEL[k]}
                </a>{" "}
                <span className="muted">
                  ({p.page_count ? `${p.page_count} pages, ` : ""}
                  {relativeTime(p.created_at)})
                </span>
              </li>
            ) : null;
          })}
        </ul>
        {latest("cover_ebook") ? (
          <img
            className="cover-thumb"
            src={fileUrl(projectId, latest("cover_ebook")!.id, true)}
            alt="The eBook front cover as built"
          />
        ) : null}
      </section>
    </div>
  );
}

// ---------- build and preview ----------

const FORMATS: { value: BuildFormat; label: string }[] = [
  { value: "epub", label: "EPUB (reflowable, accessible)" },
  { value: "pdf", label: "Print interior PDF" },
  { value: "docx", label: "Word (editable DOCX)" },
  { value: "html", label: "HTML" },
  { value: "markdown", label: "Markdown" },
];

function BuildTab({ projectId }: { projectId: string }) {
  const id = useId();
  const announce = useAnnounce();
  const [chosen, setChosen] = useState<BuildFormat[]>(["epub", "pdf", "docx", "html", "markdown"]);
  const actions = usePublishActions(projectId);
  const pubs = usePublications(projectId);
  const [showHtml, setShowHtml] = useState(false);
  const html = useHtmlPreview(projectId, showHtml);
  const [page, setPage] = useState(1);
  const nonce = pubs.dataUpdatedAt;
  const pdfPage = usePdfPage(projectId, page, nonce);
  const pages = pdfPage.data?.total ?? null;
  const standalone = (pubs.data ?? []).filter(
    (p) => !p.package_id && !p.kind.startsWith("cover") && p.kind !== "package",
  );
  return (
    <div className="stack">
      <section className="panel" aria-labelledby={`${id}-b`}>
        <h2 id={`${id}-b`}>Build</h2>
        <fieldset>
          <legend>Formats</legend>
          {FORMATS.map((f) => (
            <label className="inline-check" key={f.value}>
              <input
                type="checkbox"
                checked={chosen.includes(f.value)}
                onChange={(e) =>
                  setChosen(e.target.checked ? [...chosen, f.value] : chosen.filter((x) => x !== f.value))
                }
              />
              {f.label}
            </label>
          ))}
        </fieldset>
        <p className="hint">MOBI and AZW3 are not built: KDP takes EPUB, and no converter is installed.</p>
        <button
          type="button"
          className="btn btn-primary"
          disabled={!chosen.length || actions.build.isPending}
          onClick={() =>
            actions.build.mutate(chosen, {
              onSuccess: (r) => announce(`Built ${r.publications.length} file(s)`),
            })
          }
        >
          {actions.build.isPending ? "Building…" : "Build"}
        </button>
        {actions.build.error ? <InlineError error={actions.build.error} /> : null}
        {actions.build.data?.warnings.length ? (
          <ul className="warnings">
            {actions.build.data.warnings.map((w, i) => (
              <li key={i}>{w.message}</li>
            ))}
          </ul>
        ) : null}
        <PublicationTable projectId={projectId} items={standalone} />
      </section>
      <section className="panel" aria-labelledby={`${id}-ph`}>
        <h2 id={`${id}-ph`}>Reading preview (HTML)</h2>
        <button
          type="button"
          className="btn"
          onClick={() => (showHtml ? void html.refetch() : setShowHtml(true))}
        >
          {showHtml ? "Refresh preview" : "Show reading preview"}
        </button>
        {html.data ? (
          <>
            <p
              className={html.data.identical_to_last_export === false ? "inline-error" : "hint"}
              role="status"
            >
              {html.data.note}
            </p>
            <iframe
              className="book-preview"
              title="Reading preview of the book"
              sandbox=""
              srcDoc={html.data.html}
            />
          </>
        ) : null}
      </section>
      <section className="panel" aria-labelledby={`${id}-pp`}>
        <h2 id={`${id}-pp`}>Print preview (PDF pages)</h2>
        <p className="hint">
          These pages are pictures of the current layout, made by the same engine as the PDF, but they are not
          the PDF file itself. Open the exported PDF to check exactly what you upload.
        </p>
        <div className="page-actions">
          <button
            type="button"
            className="btn btn-small"
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
          >
            Previous page
          </button>
          <span aria-live="polite">
            Page {page}
            {pages ? ` of ${pages}` : ""}
          </span>
          <button
            type="button"
            className="btn btn-small"
            disabled={pages !== null && page >= pages}
            onClick={() => setPage(page + 1)}
          >
            Next page
          </button>
        </div>
        {pdfPage.error ? (
          <p className="inline-error">{pdfPage.error.message}</p>
        ) : pdfPage.data ? (
          <img className="pdf-page" src={pdfPage.data.url} alt={`Page ${page} of the print layout`} />
        ) : (
          <Loading label="Laying out the page" />
        )}
      </section>
    </div>
  );
}

function usePdfPage(projectId: string, page: number, nonce: number) {
  return useQuery({
    queryKey: ["publishing", "pdf-page", projectId, page, nonce],
    queryFn: async () => {
      const r = await fetch(pdfPageUrl(projectId, page, nonce));
      if (!r.ok)
        throw new Error(
          ((await r.json().catch(() => null)) as { title?: string } | null)?.title ?? "Preview failed",
        );
      return { url: URL.createObjectURL(await r.blob()), total: Number(r.headers.get("X-Page-Count") ?? 0) };
    },
    staleTime: Infinity,
  });
}

function PublicationTable({ projectId, items }: { projectId: string; items: Publication[] }) {
  if (!items.length) return <p className="muted">Nothing built yet.</p>;
  return (
    <table className="data-table">
      <caption>Built files</caption>
      <thead>
        <tr>
          <th scope="col">File</th>
          <th scope="col">Checks</th>
          <th scope="col">Fidelity</th>
          <th scope="col">Built</th>
        </tr>
      </thead>
      <tbody>
        {items.slice(0, 15).map((p) => (
          <tr key={p.id}>
            <th scope="row">
              <a
                href={fileUrl(projectId, p.id, p.kind === "pdf" || p.kind === "html")}
                target="_blank"
                rel="noreferrer"
              >
                {KIND_LABEL[p.kind] ?? p.kind}
              </a>
              {p.page_count ? <span className="muted"> · {p.page_count} pages</span> : null}
            </th>
            <td>
              <a href={reportUrl(projectId, p.id)} target="_blank" rel="noreferrer">
                {Object.entries(p.report_summary)
                  .map(([k, v]) => `${v} ${STATUS_LABEL[k] ?? k}`)
                  .join(", ") || "report"}
              </a>
            </td>
            <td>{p.fidelity ?? "-"}</td>
            <td>{relativeTime(p.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ---------- package ----------

function PackageTab({ projectId, profile }: { projectId: string; profile: Profile }) {
  const id = useId();
  const announce = useAnnounce();
  const actions = usePublishActions(projectId);
  const pubs = usePublications(projectId);
  const [result, setResult] = useState<PackageResult | null>(null);
  const last = result?.publication ?? (pubs.data ?? []).find((p) => p.kind === "package");
  const rules = profile.rules as {
    ruleset: string;
    checked_on: string;
    sources: Record<string, string>;
    not_published: string[];
  };
  const tools = profile.tools as { epubcheck: string; epubcheck_note: string };
  return (
    <div className="stack">
      <section className="panel" aria-labelledby={`${id}-p`}>
        <h2 id={`${id}-p`}>Publish package</h2>
        <p>
          Builds every format, the covers from the final page count, store details, the full preflight report,
          license and source notes, and step-by-step upload instructions into one folder.{" "}
          <strong>Nothing is uploaded or published.</strong>
        </p>
        <p className="hint">
          EPUBCheck:{" "}
          {tools.epubcheck === "available"
            ? "installed"
            : "not installed, so EPUB validation is reported as unavailable (never as passed)"}
          . {tools.epubcheck === "available" ? "" : tools.epubcheck_note}
        </p>
        <button
          type="button"
          className="btn btn-primary"
          disabled={actions.pkg.isPending}
          onClick={() =>
            actions.pkg.mutate(undefined, {
              onSuccess: (r) => {
                setResult(r);
                announce("The publish package is ready");
              },
            })
          }
        >
          {actions.pkg.isPending ? "Building the package…" : "Build the publish package"}
        </button>
        {actions.pkg.error ? <InlineError error={actions.pkg.error} /> : null}
      </section>
      {last ? (
        <section className="panel" aria-labelledby={`${id}-r`}>
          <h2 id={`${id}-r`}>Latest package</h2>
          <p>
            Built {relativeTime(last.created_at)}, {last.page_count} print pages. Checks:{" "}
            {Object.entries(last.report_summary)
              .map(([k, v]) => `${v} ${STATUS_LABEL[k] ?? k}`)
              .join(", ")}
            .
          </p>
          <div className="page-actions">
            <a
              className="btn btn-primary"
              href={packageFileUrl(projectId, last.id, "preflight-report.html", true)}
              target="_blank"
              rel="noreferrer"
            >
              Open the preflight report
            </a>
            <a
              className="btn"
              href={packageFileUrl(projectId, last.id, "KDP-UPLOAD-STEPS.md", true)}
              target="_blank"
              rel="noreferrer"
            >
              Upload steps
            </a>
            <a className="btn" href={fileUrl(projectId, last.id)}>
              Download the package (ZIP)
            </a>
          </div>
          {result ? (
            <>
              <p className="hint file-path">Folder on this computer: {result.folder}</p>
              <ul className="link-list">
                {result.files.map((f) => (
                  <li key={String(f.name)}>
                    <a
                      href={packageFileUrl(projectId, last.id, String(f.name), true)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {String(f.name)}
                    </a>{" "}
                    <span className="muted">{Math.max(1, Math.round(Number(f.bytes) / 1024))} KB</span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </section>
      ) : null}
      <section className="panel" aria-labelledby={`${id}-s`}>
        <h2 id={`${id}-s`}>Rules used</h2>
        <p>
          Rule set <strong>{rules.ruleset}</strong>, checked on {rules.checked_on}. KDP can change its
          specifications at any time; compare with the current pages before you upload.
        </p>
        <ul>
          {Object.entries(rules.sources).map(([k, v]) => (
            <li key={k}>
              <a href={v} target="_blank" rel="noreferrer">
                {k.replaceAll("_", " ")}
              </a>
            </li>
          ))}
        </ul>
        <h3>Not published by KDP (check by hand)</h3>
        <ul>
          {rules.not_published.map((x) => (
            <li key={x}>{x}</li>
          ))}
        </ul>
      </section>
    </div>
  );
}
