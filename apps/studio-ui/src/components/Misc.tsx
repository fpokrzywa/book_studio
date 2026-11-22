import { useEffect, type ReactNode } from "react";
import { Link } from "react-router";
import { useSystemInfo } from "../api/hooks";

export function usePageTitle(title: string) {
  useEffect(() => {
    document.title = `${title} | Personal Book Studio`;
  }, [title]);
}

export function PageHeader({
  title,
  intro,
  actions,
}: {
  title: string;
  intro?: ReactNode;
  actions?: ReactNode;
}) {
  usePageTitle(title);
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {intro ? <p>{intro}</p> : null}
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}

export function PrivacyBadge() {
  const info = useSystemInfo();
  const local = info.data?.privacy_mode !== "cloud_allowed";
  const label = info.isError ? "Core offline" : local ? "Local-only" : "Cloud allowed";
  return (
    <span
      className="privacy-badge"
      title={
        local
          ? "Local-only mode: nothing you write leaves this computer. Cloud AI is off."
          : "Cloud allowed: content may be sent to the AI providers you enabled."
      }
    >
      <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
        <path
          d="M8 1 2.5 3.2v4.1c0 3.3 2.3 6.3 5.5 7.2 3.2-.9 5.5-3.9 5.5-7.2V3.2L8 1Z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
        />
      </svg>
      <span>
        <span className="visually-hidden">Privacy mode: </span>
        {label}
      </span>
    </span>
  );
}

export function NotAvailable({ feature, phase, what }: { feature: string; phase: string; what: string }) {
  usePageTitle(feature);
  return (
    <section className="state" aria-labelledby="na-title">
      <h1 id="na-title">{feature}</h1>
      <p>
        <strong>Not yet implemented.</strong> {what} This arrives in Phase {phase} of the roadmap. Nothing on
        this page works yet, so there is nothing here to click.
      </p>
      <Link to="/" className="btn">
        Back to the library
      </Link>
    </section>
  );
}
