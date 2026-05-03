import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { ErrorBoundary } from './components/common/ErrorBoundary';
import './styles/tokens.css';
import './styles/app.css';

// Last-ditch: if even React mount fails, paint a diagnostic instead of staying blank.
// Uses safe DOM APIs (textContent, no innerHTML) so the error message can't inject markup.
window.addEventListener('error', (e) => {
  const root = document.getElementById('root');
  if (!root || root.firstChild) return;
  const wrap = document.createElement('div');
  wrap.style.cssText = 'padding:1.5rem;color:#ff3860;font-family:monospace;font-size:0.85rem;';
  const label = document.createElement('strong');
  label.textContent = 'JS load error: ';
  const msg = document.createElement('span');
  msg.textContent = e.error?.message || e.message || 'unknown';
  const btn = document.createElement('button');
  btn.textContent = 'Hard reload';
  btn.style.cssText = 'margin-top:1rem;display:block;background:#ff2eb6;color:#06010f;border:0;padding:0.5rem 1rem;border-radius:8px;font-weight:700;cursor:pointer;';
  btn.addEventListener('click', () => window.location.reload());
  wrap.append(label, msg, btn);
  root.appendChild(wrap);
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
