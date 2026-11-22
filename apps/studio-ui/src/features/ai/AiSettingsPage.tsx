import { useId, useState } from "react";
import {
  TASKS,
  capabilityLabel,
  useAiStatus,
  usePriceActions,
  usePrices,
  useProviderActions,
  useProviderKinds,
  useProviders,
  useRouteActions,
  useRoutes,
  useSetPrivacy,
  whereLabel,
  type AiTask,
  type Provider,
  type Route,
} from "../../api/ai";
import { useAnnounce } from "../../components/Announcer";
import { ConfirmDialog } from "../../components/Dialog";
import { PageHeader } from "../../components/Misc";
import { ErrorState, InlineError, Loading } from "../../components/States";
import { relativeTime } from "../../lib/format";

export function AiSettingsPage() {
  const status = useAiStatus();
  const providers = useProviders();
  if (status.isError) return <ErrorState error={status.error} onRetry={() => void status.refetch()} />;
  if (!status.data || !providers.data) return <Loading label="Loading AI settings" />;
  return (
    <>
      <PageHeader
        title="AI settings"
        intro="Choose which AI models Personal Book Studio may use, and whether anything may leave this computer."
      />
      <PrivacySection mode={status.data.privacy_mode} external={status.data.external_requests} />
      {status.data.secret_store.warning ? (
        <div className="banner" role="note">
          <span>
            <strong>Key storage:</strong> {status.data.secret_store.warning}
          </span>
        </div>
      ) : null}
      <ProvidersSection providers={providers.data} keyStore={status.data.secret_store.backend} />
      <RoutesSection providers={providers.data} />
      <PricesSection providers={providers.data.filter((p) => !p.local)} />
    </>
  );
}

function PrivacySection({ mode, external }: { mode: string; external: Record<string, number> }) {
  const id = useId();
  const announce = useAnnounce();
  const setPrivacy = useSetPrivacy();
  const [confirm, setConfirm] = useState(false);
  const sent = Object.entries(external);
  return (
    <section className="panel" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>Privacy</h2>
      <fieldset className="segmented">
        <legend>Where AI may run</legend>
        <label>
          <input
            type="radio"
            name={`${id}-mode`}
            checked={mode === "local_only"}
            onChange={() =>
              setPrivacy.mutate(
                { mode: "local_only", confirm: false },
                { onSuccess: () => announce("Local-only mode is on") },
              )
            }
          />
          Local only: nothing leaves this computer
        </label>
        <label>
          <input
            type="radio"
            name={`${id}-mode`}
            checked={mode === "cloud_allowed"}
            onChange={() => setConfirm(true)}
          />
          Cloud allowed, for books you approve
        </label>
      </fieldset>
      <p className="hint">
        {mode === "local_only"
          ? "Cloud providers are blocked before any connection is made. Local models (Ollama) still work."
          : "Each book must also be allowed to use each cloud provider; you are asked the first time."}{" "}
        Requests sent to the internet since Core started:{" "}
        <strong>{sent.length === 0 ? "none" : sent.map(([h, n]) => `${h} (${n})`).join(", ")}</strong>.
      </p>
      {setPrivacy.error ? <InlineError error={setPrivacy.error} /> : null}
      <ConfirmDialog
        isOpen={confirm}
        title="Allow cloud AI?"
        body="When you use a cloud model, the chapter text and your instruction are sent to that company over the internet, and their terms apply. Books still need your permission per provider. You can switch back to local-only at any time."
        confirmLabel="Allow cloud AI"
        busy={setPrivacy.isPending}
        onCancel={() => setConfirm(false)}
        onConfirm={() =>
          setPrivacy.mutate(
            { mode: "cloud_allowed", confirm: true },
            {
              onSuccess: () => {
                setConfirm(false);
                announce("Cloud AI allowed");
              },
            },
          )
        }
      />
    </section>
  );
}

function ProvidersSection({ providers, keyStore }: { providers: Provider[]; keyStore: string }) {
  const id = useId();
  const kinds = useProviderKinds();
  const actions = useProviderActions();
  const announce = useAnnounce();
  const [kind, setKind] = useState("ollama");
  const [url, setUrl] = useState("");
  const chosen = kinds.data?.find((k) => k.kind === kind);
  return (
    <section className="panel" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>Providers</h2>
      {providers.length === 0 ? (
        <p>No AI providers yet. Add a local Ollama server to start; nothing leaves this computer.</p>
      ) : (
        <div className="stack">
          {providers.map((p) => (
            <ProviderCard key={p.id} provider={p} keyStore={keyStore} />
          ))}
        </div>
      )}
      <form
        className="form add-provider"
        aria-labelledby={`${id}-add`}
        onSubmit={(e) => {
          e.preventDefault();
          actions.create.mutate(
            { kind: kind as Provider["kind"], ...(chosen?.url_editable && url ? { base_url: url } : {}) },
            {
              onSuccess: (p) => {
                setUrl("");
                announce(`Added ${p.label}`);
              },
            },
          );
        }}
      >
        <h3 id={`${id}-add`}>Add a provider</h3>
        <div className="form-row">
          <div className="field">
            <label htmlFor={`${id}-kind`}>Provider</label>
            <select id={`${id}-kind`} value={kind} onChange={(e) => setKind(e.target.value)}>
              {(kinds.data ?? []).map((k) => (
                <option key={k.kind} value={k.kind}>
                  {k.label}
                  {k.local ? "" : " (cloud)"}
                </option>
              ))}
            </select>
            {chosen ? <p className="hint">{chosen.note}</p> : null}
          </div>
          {chosen?.url_editable ? (
            <div className="field">
              <label htmlFor={`${id}-url`}>Address (optional)</label>
              <input
                id={`${id}-url`}
                value={url}
                placeholder={chosen.default_url}
                onChange={(e) => setUrl(e.target.value)}
              />
              <p className="hint">Must be on this computer, such as {chosen.default_url}.</p>
            </div>
          ) : null}
        </div>
        {actions.create.error ? <InlineError error={actions.create.error} /> : null}
        <button type="submit" className="btn btn-primary" disabled={actions.create.isPending}>
          Add provider
        </button>
      </form>
    </section>
  );
}

const KEY_TEXT: Record<Provider["key_status"], string> = {
  stored: "API key stored in the system credential store.",
  env: "API key read from an environment variable (PBS_…_API_KEY).",
  missing: "No API key yet.",
  not_needed: "No API key needed.",
};

function ProviderCard({ provider: p, keyStore }: { provider: Provider; keyStore: string }) {
  const id = useId();
  const announce = useAnnounce();
  const actions = useProviderActions();
  const [key, setKey] = useState("");
  const [manual, setManual] = useState("");
  const [declare, setDeclare] = useState<"unknown" | "declared:true" | "declared:false">("unknown");
  const [remove, setRemove] = useState(false);
  const error =
    actions.test.error ??
    actions.refresh.error ??
    actions.setKey.error ??
    actions.putModel.error ??
    actions.update.error ??
    actions.remove.error;
  const health = p.health;
  return (
    <article className="provider" aria-labelledby={`${id}-h`} data-enabled={p.enabled}>
      <header className="provider-head">
        <h3 id={`${id}-h`}>{p.label}</h3>
        <span className={p.local ? "tag" : "tag tag-gilt"}>{whereLabel(p.local, p.label)}</span>
        {!p.enabled ? <span className="tag">Turned off</span> : null}
      </header>
      <p className="muted">
        {p.base_url.startsWith("builtin:") ? "Built into Personal Book Studio." : p.base_url} ·{" "}
        {KEY_TEXT[p.key_status]}
      </p>
      <p role="status" className={health && !health.ok ? "job-error" : "muted"}>
        {health
          ? `${health.ok ? "Working" : "Not working"}: ${health.message} (checked ${relativeTime(health.checked_at)})`
          : "Connection not tested yet."}
      </p>
      <div className="page-actions">
        <button
          type="button"
          className="btn btn-small"
          disabled={actions.test.isPending}
          onClick={() =>
            actions.test.mutate(p.id, { onSuccess: (h) => announce(h.ok ? "Connection works" : h.message) })
          }
        >
          {actions.test.isPending ? "Testing…" : "Test connection"}
        </button>
        <button
          type="button"
          className="btn btn-small"
          disabled={actions.refresh.isPending}
          onClick={() =>
            actions.refresh.mutate(p.id, { onSuccess: (r) => announce(`${r.models.length} models found`) })
          }
        >
          {actions.refresh.isPending ? "Looking…" : "Find models"}
        </button>
        <button
          type="button"
          className="btn btn-small"
          onClick={() => actions.update.mutate({ id: p.id, enabled: !p.enabled })}
        >
          {p.enabled ? "Turn off" : "Turn on"}
        </button>
        <button type="button" className="btn btn-small btn-danger" onClick={() => setRemove(true)}>
          Remove
        </button>
      </div>
      {p.key_status !== "not_needed" ? (
        <form
          className="form-row"
          onSubmit={(e) => {
            e.preventDefault();
            actions.setKey.mutate(
              { id: p.id, api_key: key },
              {
                onSuccess: () => {
                  setKey("");
                  announce("API key stored");
                },
              },
            );
          }}
        >
          <div className="field">
            <label htmlFor={`${id}-key`}>{p.key_status === "stored" ? "Replace API key" : "API key"}</label>
            <input
              id={`${id}-key`}
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={key}
              onChange={(e) => setKey(e.target.value)}
            />
            <p className="hint">
              Kept in{" "}
              {keyStore === "keyring" ? "your system's credential store" : `the “${keyStore}” key store`},
              never in the book database, backups or exports.
            </p>
          </div>
          <div className="page-actions">
            <button
              type="submit"
              className="btn btn-small"
              disabled={key.trim().length < 8 || actions.setKey.isPending}
            >
              Store key
            </button>
            {p.key_status === "stored" ? (
              <button type="button" className="btn btn-small" onClick={() => actions.deleteKey.mutate(p.id)}>
                Remove key
              </button>
            ) : null}
          </div>
        </form>
      ) : null}
      {error ? <InlineError error={error} /> : null}
      <details>
        <summary>Models ({p.models.length})</summary>
        {p.models.length === 0 ? (
          <p className="muted">No models yet. Use Find models, or add one by name below.</p>
        ) : (
          <table className="data-table">
            <caption className="visually-hidden">Models for {p.label}</caption>
            <thead>
              <tr>
                <th scope="col">Model</th>
                <th scope="col">Context</th>
                <th scope="col">Longest answer</th>
                <th scope="col">Structured output</th>
                <th scope="col">Source</th>
              </tr>
            </thead>
            <tbody>
              {p.models.map((m) => (
                <tr key={m.name}>
                  <th scope="row">{m.display_name ?? m.name}</th>
                  <td>{m.context_tokens ? `${m.context_tokens.toLocaleString()} tokens` : "Unknown"}</td>
                  <td>
                    {m.max_output_tokens ? `${m.max_output_tokens.toLocaleString()} tokens` : "Unknown"}
                  </td>
                  <td>{capabilityLabel(m.capabilities.structured_output)}</td>
                  <td>{m.source === "manual" ? "Added by you" : "Found"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <form
          className="form-row"
          onSubmit={(e) => {
            e.preventDefault();
            actions.putModel.mutate(
              { id: p.id, name: manual.trim(), structured_output: declare },
              { onSuccess: () => setManual("") },
            );
          }}
        >
          <div className="field">
            <label htmlFor={`${id}-model`}>Add or update a model by its exact ID</label>
            <input
              id={`${id}-model`}
              value={manual}
              spellCheck={false}
              onChange={(e) => setManual(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor={`${id}-so`}>Supports structured (JSON) output?</label>
            <select
              id={`${id}-so`}
              value={declare}
              onChange={(e) => setDeclare(e.target.value as typeof declare)}
            >
              <option value="unknown">Don't know (answers are checked as text)</option>
              <option value="declared:true">Yes, per the provider's documentation</option>
              <option value="declared:false">No</option>
            </select>
          </div>
          <button
            type="submit"
            className="btn btn-small"
            disabled={!manual.trim() || /\s/.test(manual.trim())}
          >
            Save model
          </button>
        </form>
      </details>
      <ConfirmDialog
        isOpen={remove}
        title={`Remove ${p.label}?`}
        body="Its stored API key is deleted and task defaults that use it are cleared. Past jobs keep their history."
        confirmLabel="Remove provider"
        danger
        busy={actions.remove.isPending}
        onCancel={() => setRemove(false)}
        onConfirm={() => actions.remove.mutate(p.id, { onSuccess: () => setRemove(false) })}
      />
    </article>
  );
}

function RoutesSection({ providers }: { providers: Provider[] }) {
  const id = useId();
  const routes = useRoutes();
  const choices = providers
    .filter((p) => p.enabled)
    .flatMap((p) => p.models.map((m) => ({ value: `${p.id}::${m.name}`, label: `${m.name} (${p.label})` })));
  return (
    <section className="panel" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>Default model per task</h2>
      <p className="hint">
        Used when you don't pick a model in the editor. Choosing a model in the editor always wins; nothing
        ever switches to a different provider on its own.
      </p>
      {choices.length === 0 ? (
        <p className="muted">Add a provider and find its models first.</p>
      ) : (
        <table className="data-table">
          <caption className="visually-hidden">Default model for each task</caption>
          <thead>
            <tr>
              <th scope="col">Task</th>
              <th scope="col">Model</th>
              <th scope="col">Temperature</th>
              <th scope="col">Longest answer (tokens)</th>
              <th scope="col">
                <span className="visually-hidden">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {TASKS.map((t) => (
              <RouteRow
                key={`${t.value}-${routes.data?.find((r) => r.task === t.value)?.updated_at ?? "none"}`}
                task={t.value}
                label={t.label}
                route={routes.data?.find((r) => r.task === t.value)}
                choices={choices}
              />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function RouteRow({
  task,
  label,
  route,
  choices,
}: {
  task: AiTask;
  label: string;
  route: Route | undefined;
  choices: { value: string; label: string }[];
}) {
  const id = useId();
  const actions = useRouteActions();
  const [choice, setChoice] = useState(route ? `${route.provider_id}::${route.model_name}` : "");
  const [temp, setTemp] = useState(route?.temperature?.toString() ?? "");
  const [max, setMax] = useState(route?.max_output_tokens?.toString() ?? "");
  const error = actions.put.error ?? actions.remove.error;
  return (
    <tr>
      <th scope="row">{label}</th>
      <td>
        <label className="visually-hidden" htmlFor={`${id}-m`}>
          Model for {label}
        </label>
        <select id={`${id}-m`} value={choice} onChange={(e) => setChoice(e.target.value)}>
          <option value="">None</option>
          {choices.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
        {error ? <InlineError error={error} /> : null}
      </td>
      <td>
        <label className="visually-hidden" htmlFor={`${id}-t`}>
          Temperature for {label} (blank uses the model's default)
        </label>
        <input
          id={`${id}-t`}
          type="number"
          min={0}
          max={2}
          step={0.1}
          value={temp}
          placeholder="Default"
          onChange={(e) => setTemp(e.target.value)}
        />
      </td>
      <td>
        <label className="visually-hidden" htmlFor={`${id}-x`}>
          Longest answer for {label}
        </label>
        <input
          id={`${id}-x`}
          type="number"
          min={16}
          max={200000}
          value={max}
          placeholder="2048"
          onChange={(e) => setMax(e.target.value)}
        />
      </td>
      <td>
        <button
          type="button"
          className="btn btn-small"
          disabled={actions.put.isPending}
          onClick={() => {
            if (!choice) {
              actions.remove.mutate(task);
              return;
            }
            const [provider_id = "", model_name = ""] = choice.split("::");
            actions.put.mutate({
              task,
              provider_id,
              model_name,
              temperature: temp === "" ? null : Number(temp),
              max_output_tokens: max === "" ? null : Number(max),
            });
          }}
        >
          Save
        </button>
      </td>
    </tr>
  );
}

function PricesSection({ providers }: { providers: Provider[] }) {
  const id = useId();
  if (providers.length === 0) return null;
  return (
    <section className="panel" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>Prices for cost estimates</h2>
      <p className="hint">
        Personal Book Studio does not ship prices, because they change. Copy them from the provider's pricing
        page; until you do, costs are shown as unknown. Local models have no API charge.
      </p>
      {providers.map((p) => (
        <ProviderPrices key={p.id} provider={p} />
      ))}
    </section>
  );
}

function ProviderPrices({ provider }: { provider: Provider }) {
  const id = useId();
  const prices = usePrices(provider.id);
  const actions = usePriceActions(provider.id);
  const today = new Date().toISOString().slice(0, 10);
  const [form, setForm] = useState({
    model_name: "",
    input_per_mtok: "",
    output_per_mtok: "",
    currency: "USD",
    source_url: "",
    as_of: today,
  });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [k]: e.target.value });
  return (
    <div className="stack">
      <h3>{provider.label}</h3>
      {(prices.data ?? []).length > 0 ? (
        <table className="data-table">
          <caption className="visually-hidden">Prices entered for {provider.label}</caption>
          <thead>
            <tr>
              <th scope="col">Model</th>
              <th scope="col">Input per million tokens</th>
              <th scope="col">Output per million tokens</th>
              <th scope="col">As of</th>
              <th scope="col">
                <span className="visually-hidden">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {prices.data?.map((r) => (
              <tr key={r.id}>
                <th scope="row">{r.model_name}</th>
                <td>
                  {r.input_per_mtok} {r.currency}
                </td>
                <td>
                  {r.output_per_mtok} {r.currency}
                </td>
                <td>
                  {r.as_of}
                  {r.source_url ? (
                    <>
                      {" "}
                      (
                      <a href={r.source_url} rel="noreferrer noopener" target="_blank">
                        source
                      </a>
                      )
                    </>
                  ) : null}
                </td>
                <td>
                  <button type="button" className="btn btn-small" onClick={() => actions.remove.mutate(r.id)}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted">No prices entered.</p>
      )}
      <form
        className="form-row"
        onSubmit={(e) => {
          e.preventDefault();
          actions.put.mutate(
            { ...form, source_url: form.source_url || null },
            {
              onSuccess: () => setForm({ ...form, model_name: "", input_per_mtok: "", output_per_mtok: "" }),
            },
          );
        }}
      >
        <div className="field">
          <label htmlFor={`${id}-m`}>Model ID</label>
          <input id={`${id}-m`} value={form.model_name} onChange={set("model_name")} list={`${id}-models`} />
          <datalist id={`${id}-models`}>
            {provider.models.map((m) => (
              <option key={m.name} value={m.name} />
            ))}
          </datalist>
        </div>
        <div className="field">
          <label htmlFor={`${id}-i`}>Input price per million tokens</label>
          <input
            id={`${id}-i`}
            inputMode="decimal"
            value={form.input_per_mtok}
            onChange={set("input_per_mtok")}
          />
        </div>
        <div className="field">
          <label htmlFor={`${id}-o`}>Output price per million tokens</label>
          <input
            id={`${id}-o`}
            inputMode="decimal"
            value={form.output_per_mtok}
            onChange={set("output_per_mtok")}
          />
        </div>
        <div className="field">
          <label htmlFor={`${id}-c`}>Currency</label>
          <input id={`${id}-c`} value={form.currency} maxLength={3} onChange={set("currency")} />
        </div>
        <div className="field">
          <label htmlFor={`${id}-s`}>Pricing page (https)</label>
          <input id={`${id}-s`} type="url" value={form.source_url} onChange={set("source_url")} />
        </div>
        <div className="field">
          <label htmlFor={`${id}-d`}>Price as of</label>
          <input id={`${id}-d`} type="date" value={form.as_of} onChange={set("as_of")} />
        </div>
        {actions.put.error ? <InlineError error={actions.put.error} /> : null}
        <button
          type="submit"
          className="btn btn-small"
          disabled={
            !form.model_name || !form.input_per_mtok || !form.output_per_mtok || actions.put.isPending
          }
        >
          Save price
        </button>
      </form>
    </div>
  );
}
