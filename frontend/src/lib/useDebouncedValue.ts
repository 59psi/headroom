import { useEffect, useState } from 'react';

/**
 * `value`, but only after it has held still for `delayMs`.
 *
 * For a query keyed on what is being typed: without this, a colorway lookup
 * scoped to the model name refetched on every keystroke of "Odysea Hydro" —
 * twelve requests for one field, each answering a question already obsolete.
 */
export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setSettled(value), delayMs);
    return () => clearTimeout(t);
  }, [value, delayMs]);
  return settled;
}
