import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { portalToBody } from '../common/ModalPortal';

/**
 * Transient confirmation that something happened in the background.
 *
 * A save used to be acknowledged — when it was acknowledged at all — by the
 * button text flipping back from "Saving…", which is the same thing it does
 * when the request fails and nobody reads the error below the fold. A toast
 * says "Saved" where the eye already is, and goes away on its own.
 *
 * Toasts are for OUTCOMES, never for anything the person has to act on or
 * read later: a failed save still renders its `ErrorNote` in place (a toast
 * that disappears in seven seconds is not an error report), and the toast
 * only points at it.
 */
export type ToastTone = 'success' | 'error' | 'info';

export interface ToastOptions {
  /** One optional follow-up, e.g. "Undo" or "View". */
  action?: { label: string; onClick: () => void };
  /** Milliseconds on screen. Defaults: 3.5s, errors 7s. */
  duration?: number;
}

interface ToastItem extends ToastOptions {
  id: number;
  tone: ToastTone;
  message: ReactNode;
}

export interface ToastApi {
  success: (message: ReactNode, options?: ToastOptions) => void;
  error: (message: ReactNode, options?: ToastOptions) => void;
  info: (message: ReactNode, options?: ToastOptions) => void;
}

const NOOP: ToastApi = { success: () => {}, error: () => {}, info: () => {} };

const ToastContext = createContext<ToastApi | null>(null);

/**
 * The toast API. Outside a `ToastProvider` it is a silent no-op rather than a
 * throw: a toast is a courtesy on top of a result the component already
 * renders, so a component mounted without the provider (a unit test that only
 * cares about its own markup) loses nothing it needed.
 */
export function useToast(): ToastApi {
  return useContext(ToastContext) ?? NOOP;
}

const MAX_VISIBLE = 3;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setItems(list => list.filter(t => t.id !== id));
  }, []);

  const push = useCallback((tone: ToastTone, message: ReactNode, options: ToastOptions = {}) => {
    const id = nextId.current++;
    // Newest last; the oldest falls off once three are up, so a burst of
    // saves never stacks a column of toasts over the page.
    setItems(list => [...list, { id, tone, message, ...options }].slice(-MAX_VISIBLE));
  }, []);

  const api = useMemo<ToastApi>(() => ({
    success: (m, o) => push('success', m, o),
    error: (m, o) => push('error', m, o),
    info: (m, o) => push('info', m, o),
  }), [push]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      {portalToBody(
        // Always mounted, even empty: a live region only announces changes to
        // a region that already existed when the change happened.
        <div className="hr-toasts" role="region" aria-label="Notifications">
          {items.map(t => <Toast key={t.id} item={t} onDismiss={dismiss} />)}
        </div>,
      )}
    </ToastContext.Provider>
  );
}

function Toast({ item, onDismiss }: { item: ToastItem; onDismiss: (id: number) => void }) {
  const duration = item.duration ?? (item.tone === 'error' ? 7000 : 3500);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (paused) return;
    const t = window.setTimeout(() => onDismiss(item.id), duration);
    return () => window.clearTimeout(t);
  }, [paused, duration, item.id, onDismiss]);

  return (
    <div
      className={`hr-toast is-${item.tone}`}
      // An error interrupts; everything else waits its turn.
      role={item.tone === 'error' ? 'alert' : 'status'}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <span className="hr-toast-icon" aria-hidden="true">
        {item.tone === 'success' ? '✓' : item.tone === 'error' ? '!' : 'i'}
      </span>
      <span className="hr-toast-msg">{item.message}</span>
      {item.action && (
        <button
          type="button"
          className="hr-toast-action"
          onClick={() => { item.action!.onClick(); onDismiss(item.id); }}
        >
          {item.action.label}
        </button>
      )}
      <button
        type="button"
        className="hr-toast-close"
        aria-label="Dismiss notification"
        onClick={() => onDismiss(item.id)}
      >
        ×
      </button>
    </div>
  );
}
