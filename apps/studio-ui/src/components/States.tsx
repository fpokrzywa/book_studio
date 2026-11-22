import type { ReactNode } from "react";
import { errorMessage } from "../api/client";

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <p className="muted" role="status">
      {label}…
    </p>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="state" aria-label={title}>
      <h2>{title}</h2>
      {children ? <p>{children}</p> : null}
      {action}
    </section>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { title, detail } = errorMessage(error);
  return (
    <section className="state state-error" role="alert">
      <h2>{title}</h2>
      {detail ? <p>{detail}</p> : null}
      {onRetry ? (
        <button type="button" className="btn" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </section>
  );
}

export function InlineError({ error, children }: { error: unknown; children?: ReactNode }) {
  const { title, detail } = errorMessage(error);
  return (
    <div className="inline-error" role="alert">
      <span>
        <strong>{title}</strong> {detail}
      </span>
      {children}
    </div>
  );
}
