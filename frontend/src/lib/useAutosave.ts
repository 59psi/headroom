import { useCallback, useEffect, useRef, useState } from 'react';
import type { SaveStatus } from '../components/ui/SaveState';

/**
 * Save a value shortly after it stops changing — for free text (notes) where
 * a Save button is one more thing to forget on the way out of the page.
 *
 * Mount it with the value AS LOADED: the first render's value is the baseline
 * and is never sent back. (Render the editor only once the server value is in
 * hand, so the baseline is the real one and not an empty placeholder.)
 *
 * Guarantees, each of which a naive debounce gets wrong:
 * - Saves never overlap. A slow request and a new keystroke queue behind each
 *   other rather than racing, so an older value can never land after a newer
 *   one and silently win.
 * - `flush()` saves NOW (on blur, on Cmd+Enter), and unmounting flushes too:
 *   navigating away two keystrokes after the last pause does not lose them.
 * - "Saved" is only reported for the value actually on screen. Typing during
 *   a save reports "Unsaved changes" until the follow-up save lands.
 */
export function useAutosave<T>(
  value: T,
  save: (value: T) => Promise<unknown>,
  {
    delay = 900,
    isEqual = Object.is as (a: T, b: T) => boolean,
    enabled = true,
  }: { delay?: number; isEqual?: (a: T, b: T) => boolean; enabled?: boolean } = {},
) {
  const [status, setStatus] = useState<SaveStatus>('idle');
  const [error, setError] = useState<unknown>(null);
  // Bumps on every completed save, so a SaveState can re-show "Saved".
  const [savedCount, setSavedCount] = useState(0);

  const saved = useRef(value);
  const latest = useRef(value);
  latest.current = value;
  const saveRef = useRef(save);
  saveRef.current = save;
  const equal = useRef(isEqual);
  equal.current = isEqual;
  const timer = useRef<number | undefined>(undefined);
  const chain = useRef<Promise<void>>(Promise.resolve());
  const mounted = useRef(true);

  const flush = useCallback((): Promise<void> => {
    window.clearTimeout(timer.current);
    // Queue behind whatever is in flight; decide what to send only when it is
    // our turn, so the value sent is the newest one at that moment.
    chain.current = chain.current.then(async () => {
      const v = latest.current;
      if (equal.current(v, saved.current)) {
        if (mounted.current) setStatus(s => (s === 'pending' ? 'saved' : s));
        return;
      }
      if (mounted.current) setStatus('saving');
      try {
        await saveRef.current(v);
        saved.current = v;
        if (!mounted.current) return;
        setError(null);
        setSavedCount(c => c + 1);
        setStatus(equal.current(latest.current, v) ? 'saved' : 'pending');
      } catch (e) {
        if (!mounted.current) return;
        setError(e);
        setStatus('error');
      }
    });
    return chain.current;
  }, []);

  useEffect(() => {
    if (!enabled) return;
    if (equal.current(value, saved.current)) return;
    setStatus(s => (s === 'saving' ? s : 'pending'));
    timer.current = window.setTimeout(() => { void flush(); }, delay);
    return () => window.clearTimeout(timer.current);
  }, [value, enabled, delay, flush]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      window.clearTimeout(timer.current);
      if (!equal.current(latest.current, saved.current)) void flush();
    };
  }, [flush]);

  return { status, error, flush, savedCount };
}
