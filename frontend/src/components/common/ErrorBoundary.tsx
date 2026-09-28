import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

interface State {
  err: Error | null;
  info: ErrorInfo | null;
}

/**
 * Catch-all error boundary so a render-time exception shows a red panel
 * with the message + stack instead of a blank page. Helpful for diagnosing
 * the iOS-Safari-blank-screen class of bugs where there's no console.
 *
 * Styled by `.hr-crash*` in app.css like everything else. It was inline
 * styles with the palette typed out as hex, as if it had to survive without
 * the stylesheet — but main.tsx imports every sheet before React mounts, so
 * a RENDER crash always has them. (The case with no stylesheet — the bundle
 * failing to run at all — is main.tsx's own bare fallback, not this.)
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { err: null, info: null };

  static getDerivedStateFromError(err: Error): Partial<State> {
    return { err };
  }

  componentDidCatch(err: Error, info: ErrorInfo) {
    console.error('Headroom render crash:', err, info);
    this.setState({ info });
  }

  reset = () => this.setState({ err: null, info: null });

  render() {
    if (!this.state.err) return this.props.children;
    return (
      <div className="hr-crash" role="alert">
        <h2 className="hr-crash-title">App crashed during render</h2>
        <p className="hr-crash-message">
          <strong>{this.state.err.name}:</strong> {this.state.err.message}
        </p>
        {this.state.err.stack && <pre className="hr-crash-trace">{this.state.err.stack}</pre>}
        {this.state.info?.componentStack && (
          <details className="hr-crash-details">
            <summary>Component stack</summary>
            <pre className="hr-crash-trace">{this.state.info.componentStack}</pre>
          </details>
        )}
        <div className="hr-crash-actions">
          <button type="button" className="btn btn-danger" onClick={() => window.location.reload()}>
            Hard reload
          </button>
          <button type="button" className="btn btn-outline-secondary" onClick={this.reset}>
            Try again
          </button>
        </div>
      </div>
    );
  }
}
