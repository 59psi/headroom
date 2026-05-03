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
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { err: null, info: null };

  static getDerivedStateFromError(err: Error): Partial<State> {
    return { err };
  }

  componentDidCatch(err: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error('Headroom render crash:', err, info);
    this.setState({ info });
  }

  reset = () => this.setState({ err: null, info: null });

  render() {
    if (!this.state.err) return this.props.children;
    return (
      <div style={{
        padding: '1.5rem 1rem', maxWidth: 720, margin: '2rem auto',
        background: 'rgba(255, 56, 96, 0.12)',
        border: '1px solid rgba(255, 56, 96, 0.5)',
        borderRadius: 14, color: '#ffb1c1',
        fontFamily: 'system-ui, sans-serif',
      }}>
        <h2 style={{
          fontFamily: 'monospace', color: '#ff3860', fontSize: '1.1rem',
          letterSpacing: '0.04em', textTransform: 'uppercase', marginTop: 0,
        }}>App crashed during render</h2>
        <p style={{ color: '#f5e9ff', whiteSpace: 'pre-wrap' }}>
          <strong>{this.state.err.name}:</strong> {this.state.err.message}
        </p>
        {this.state.err.stack && (
          <pre style={{
            background: 'rgba(0,0,0,0.4)', padding: '0.75rem',
            borderRadius: 8, overflow: 'auto', fontSize: '0.75rem',
            maxHeight: 240,
          }}>{this.state.err.stack}</pre>
        )}
        {this.state.info?.componentStack && (
          <details style={{ marginTop: '1rem' }}>
            <summary style={{ cursor: 'pointer', color: '#00f0ff' }}>
              Component stack
            </summary>
            <pre style={{
              background: 'rgba(0,0,0,0.4)', padding: '0.75rem',
              borderRadius: 8, overflow: 'auto', fontSize: '0.7rem',
              marginTop: '0.5rem',
            }}>{this.state.info.componentStack}</pre>
          </details>
        )}
        <div style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem' }}>
          <button
            type="button"
            onClick={() => window.location.reload()}
            style={{
              background: '#ff2eb6', color: '#06010f', border: 'none',
              borderRadius: 8, padding: '0.5rem 1rem', fontWeight: 700,
              cursor: 'pointer',
            }}
          >Hard reload</button>
          <button
            type="button"
            onClick={this.reset}
            style={{
              background: 'transparent', color: '#b6a3d6',
              border: '1px solid #2a1659', borderRadius: 8,
              padding: '0.5rem 1rem', cursor: 'pointer',
            }}
          >Try again</button>
        </div>
      </div>
    );
  }
}
