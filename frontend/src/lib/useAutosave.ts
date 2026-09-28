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
 * - "Is there anything to send?" is asked against what the server holds now
 *   AND what it will hold once the request in flight lands (`unsent`).
 *   Typing an edit and then undoing it while the edit's save is still in
 *   flight means the server is about to hold the edit — so the undo must be
 *   sent after, or the discarded edit silently wins. And the value on the
 *   wire is not safe until it lands: if that request fails, an unmount or a
 *   later keystroke still gets its own save.
 * - Typing back to exactly what the server holds leaves nothing unsaved and
 *   nothing failed, so it clears "Unsaved changes" / "Not saved" instead of
 *   leaving either standing over a field whose content is safe.
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
  // The value of the request on the wire, boxed so a `T` that is itself
  // null/undefined still reads as "something is in flight".
  const inflight = useRef<{ value: T } | null>(null);

  /**
   * Does `v` still need a save queued for it? Yes unless the server holds it
   * now AND will still hold it once the request in flight (if any) lands.
   *
   * Both halves matter. Against the confirmed save alone, an edit undone
   * while that edit is on the wire looks like "nothing to send" — and the
   * discarded edit silently wins. Against the in-flight value alone, the
   * value on the wire looks settled before it has landed — and when that
   * request fails, the edit gets no second try: none on an unmount (blur,
   * then Back, the usual way out on a phone), where no card is left to say
   * "Not saved", and none for keystrokes typed after it left. A queued save
   * that turns out unneeded costs nothing: `flush` re-checks against the
   * confirmed save at its turn and sends only if the two still differ.
   */
  const unsent = useCallback(
    (v: T) =>
      !equal.current(v, saved.current)
      || (inflight.current !== null && !equal.current(v, inflight.current.value)),
    [],
  );

  const flush = useCallback((): Promise<void> => {
    window.clearTimeout(timer.current);
    // Queue behind whatever is in flight; decide what to send only when it is
    // our turn, so the value sent is the newest one at that moment.
    chain.current = chain.current.then(async () => {
      const v = latest.current;
      if (equal.current(v, saved.current)) {
        // Nothing to send: the screen already matches the server. A failure
        // from an edit since undone no longer describes anything on screen.
        if (mounted.current) {
          setStatus(s => (s === 'pending' ? 'saved' : s === 'error' ? 'idle' : s));
          setError(null);
        }
        return;
      }
      if (mounted.current) setStatus('saving');
      inflight.current = { value: v };
      try {
        await saveRef.current(v);
        saved.current = v;
        if (!mounted.current) return;
        setError(null);
        setSavedCount(c => c + 1);
        // Not equal means the person typed during the save; that newer
        // value's own debounce (or a flush queued behind this one) sends it.
        setStatus(equal.current(latest.current, v) ? 'saved' : 'pending');
      } catch (e) {
        if (!mounted.current) return;
        setError(e);
        setStatus('error');
      } finally {
        inflight.current = null;
      }
    });
    return chain.current;
  }, []);

  useEffect(() => {
    if (!enabled) return;
    if (!unsent(value)) {
      // Back to what the server holds, with nothing on the wire (a request
      // in flight always differs from the confirmed save, so "not unsent"
      // implies none): clear any "Unsaved changes" / "Not saved" left from
      // the edit just undone.
      setStatus(s => (s === 'pending' || s === 'error' ? 'idle' : s));
      setError(null);
      return;
    }
    setStatus(s => (s === 'saving' ? s : 'pending'));
    timer.current = window.setTimeout(() => { void flush(); }, delay);
    return () => window.clearTimeout(timer.current);
  }, [value, enabled, delay, flush, unsent]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      window.clearTimeout(timer.current);
      if (unsent(latest.current)) void flush();
    };
  }, [flush, unsent]);

  return { status, error, flush, savedCount };
}
