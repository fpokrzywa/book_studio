import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  resetKey?: string;
}
interface State {
  error: Error | null;
}

/** Catches render errors so one broken screen never blanks the whole app. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Local console only; nothing is reported anywhere.
    console.error("UI error", error, info.componentStack);
  }

  componentDidUpdate(prev: Props) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (this.state.error) {
      return (
        <section className="state state-error" role="alert">
          <h2>This screen hit a problem and stopped.</h2>
          <p>
            Your saved work is safe: it is stored by Core, not by this page. Unsaved text on this screen may
            be lost. Reload to continue.
          </p>
          <p className="muted">Error: {this.state.error.message}</p>
          <button type="button" className="btn" onClick={() => window.location.reload()}>
            Reload
          </button>
        </section>
      );
    }
    return this.props.children;
  }
}
