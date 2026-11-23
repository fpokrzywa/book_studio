import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState, type ReactNode } from "react";
import { useAuthState, useSetup, useSignIn, authKey, type AuthState } from "../../api/auth";
import { onSignedOut } from "../../api/client";
import { ErrorState, InlineError, Loading } from "../../components/States";

/**
 * Nothing in the studio renders until Core says this browser is signed in. When no account exists
 * yet, the first visitor creates it with the one-time setup code from the server.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const state = useAuthState();
  const qc = useQueryClient();
  useEffect(() => onSignedOut(() => void qc.invalidateQueries({ queryKey: authKey })), [qc]);
  if (state.isError && !state.data)
    return <ErrorState error={state.error} onRetry={() => void state.refetch()} />;
  if (!state.data) return <Loading label="Checking your sign-in" />;
  if (state.data.signed_in) return <>{children}</>;
  return (
    <main className="auth-page" id="main">
      <div className="auth-card">
        <p className="auth-brand">Personal Book Studio</p>
        {state.data.setup_required ? <SetupForm state={state.data} /> : <SignInForm />}
      </div>
    </main>
  );
}

function SignInForm() {
  const id = useId();
  const signIn = useSignIn();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  useEffect(() => {
    document.title = "Sign in | Personal Book Studio";
  }, []);
  return (
    <form
      aria-labelledby={`${id}-h`}
      onSubmit={(e) => {
        e.preventDefault();
        signIn.mutate({ username: username.trim(), password });
      }}
    >
      <h1 id={`${id}-h`}>Sign in</h1>
      {signIn.error ? <InlineError error={signIn.error} /> : null}
      <div className="field">
        <label htmlFor={`${id}-u`}>Username</label>
        <input
          id={`${id}-u`}
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
        />
      </div>
      <div className="field">
        <label htmlFor={`${id}-p`}>Password</label>
        <input
          id={`${id}-p`}
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </div>
      <button type="submit" className="btn btn-primary" disabled={signIn.isPending || !username || !password}>
        {signIn.isPending ? "Signing in…" : "Sign in"}
      </button>
      <p className="hint">
        Forgot the password? Whoever runs the server can set a new one with{" "}
        <code>python -m pbs_core reset-password</code>.
      </p>
    </form>
  );
}

function SetupForm({ state }: { state: AuthState }) {
  const id = useId();
  const setup = useSetup();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [code, setCode] = useState("");
  const mismatch = repeat.length > 0 && repeat !== password;
  useEffect(() => {
    document.title = "Create your account | Personal Book Studio";
  }, []);
  return (
    <form
      aria-labelledby={`${id}-h`}
      onSubmit={(e) => {
        e.preventDefault();
        if (!mismatch) setup.mutate({ username: username.trim(), password, setup_code: code.trim() });
      }}
    >
      <h1 id={`${id}-h`}>Create your studio account</h1>
      <p>
        This studio has no account yet. The account you create here is the only one, and it can open every
        book on this {state.deployment === "server" ? "server" : "computer"}.
      </p>
      {setup.error ? <InlineError error={setup.error} /> : null}
      <div className="field">
        <label htmlFor={`${id}-code`}>Setup code</label>
        <input
          id={`${id}-code`}
          autoComplete="one-time-code"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          aria-describedby={`${id}-code-hint`}
          required
        />
        <p className="hint" id={`${id}-code-hint`}>
          Copy it from <code>runtime/setup-code.txt</code> in the studio&apos;s data folder. With Docker:{" "}
          <code>docker compose exec app cat /data/runtime/setup-code.txt</code>
        </p>
      </div>
      <div className="field">
        <label htmlFor={`${id}-u`}>Username</label>
        <input
          id={`${id}-u`}
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          aria-describedby={`${id}-u-hint`}
          required
        />
        <p className="hint" id={`${id}-u-hint`}>
          Letters, digits, dots, dashes, underscores or @.
        </p>
      </div>
      <div className="field">
        <label htmlFor={`${id}-p`}>Password</label>
        <input
          id={`${id}-p`}
          type="password"
          autoComplete="new-password"
          minLength={state.password_min_length}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          aria-describedby={`${id}-p-hint`}
          required
        />
        <p className="hint" id={`${id}-p-hint`}>
          At least {state.password_min_length} characters. A few unrelated words work well.
        </p>
      </div>
      <div className="field">
        <label htmlFor={`${id}-r`}>Repeat the password</label>
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
            The two passwords are different.
          </p>
        ) : null}
      </div>
      <button
        type="submit"
        className="btn btn-primary"
        disabled={setup.isPending || mismatch || !username || !password || !code}
      >
        {setup.isPending ? "Creating…" : "Create account"}
      </button>
    </form>
  );
}
