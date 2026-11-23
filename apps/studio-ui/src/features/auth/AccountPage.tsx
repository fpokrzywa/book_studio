import { useId, useState } from "react";
import { useAuthState, useChangePassword, useSignOut, useSignOutOthers } from "../../api/auth";
import { useAnnounce } from "../../components/Announcer";
import { PageHeader, usePageTitle } from "../../components/Misc";
import { InlineError } from "../../components/States";

export function AccountPage() {
  const id = useId();
  const state = useAuthState();
  const change = useChangePassword();
  const others = useSignOutOthers();
  const signOut = useSignOut();
  const announce = useAnnounce();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  usePageTitle("Account");
  const mismatch = repeat.length > 0 && repeat !== next;
  const min = state.data?.password_min_length ?? 12;
  return (
    <>
      <PageHeader
        title="Account"
        intro={`Signed in as ${state.data?.username ?? "…"}. Sessions end after a period without use, and always after two weeks.`}
      />
      <div className="stack">
        <section className="panel" aria-labelledby={`${id}-pw`}>
          <h2 id={`${id}-pw`}>Change password</h2>
          <p className="hint">Changing it signs out every other browser.</p>
          {change.error ? <InlineError error={change.error} /> : null}
          {change.data ? (
            <p role="status">
              Password changed.{" "}
              {change.data.signed_out
                ? `${change.data.signed_out} other session(s) were signed out.`
                : "No other browser was signed in."}
            </p>
          ) : null}
          <form
            className="auth-form"
            onSubmit={(e) => {
              e.preventDefault();
              if (mismatch) return;
              change.mutate(
                { current_password: current, new_password: next },
                {
                  onSuccess: () => {
                    setCurrent("");
                    setNext("");
                    setRepeat("");
                    announce("Password changed");
                  },
                },
              );
            }}
          >
            <div className="field">
              <label htmlFor={`${id}-c`}>Current password</label>
              <input
                id={`${id}-c`}
                type="password"
                autoComplete="current-password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                required
              />
            </div>
            <div className="field">
              <label htmlFor={`${id}-n`}>New password</label>
              <input
                id={`${id}-n`}
                type="password"
                autoComplete="new-password"
                minLength={min}
                value={next}
                onChange={(e) => setNext(e.target.value)}
                aria-describedby={`${id}-n-hint`}
                required
              />
              <p className="hint" id={`${id}-n-hint`}>
                At least {min} characters.
              </p>
            </div>
            <div className="field">
              <label htmlFor={`${id}-r`}>Repeat the new password</label>
              <input
                id={`${id}-r`}
                type="password"
                autoComplete="new-password"
                value={repeat}
                onChange={(e) => setRepeat(e.target.value)}
                aria-invalid={mismatch}
                aria-describedby={mismatch ? `${id}-r-err` : undefined}
                required
              />
              {mismatch ? (
                <p className="inline-error" id={`${id}-r-err`}>
                  The two new passwords are different.
                </p>
              ) : null}
            </div>
            <button type="submit" className="btn btn-primary" disabled={change.isPending || mismatch}>
              Change password
            </button>
          </form>
        </section>
        <section className="panel" aria-labelledby={`${id}-s`}>
          <h2 id={`${id}-s`}>Sessions</h2>
          {(others.error ?? signOut.error) ? <InlineError error={others.error ?? signOut.error} /> : null}
          {others.data ? (
            <p role="status">
              {others.data.signed_out
                ? `${others.data.signed_out} other session(s) signed out.`
                : "No other browser was signed in."}
            </p>
          ) : null}
          <div className="page-actions">
            <button type="button" className="btn" disabled={others.isPending} onClick={() => others.mutate()}>
              Sign out other browsers
            </button>
            <button
              type="button"
              className="btn"
              disabled={signOut.isPending}
              onClick={() => signOut.mutate()}
            >
              Sign out
            </button>
          </div>
        </section>
      </div>
    </>
  );
}
