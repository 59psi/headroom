import { useEffect, useState } from 'react';

/**
 * The inline "Saving… / Saved" note beside a field that saves itself.
 *
 * Autosave with no acknowledgement is worse than a Save button: the person
 * cannot tell whether the change took, so they reload to check. This is the
 * acknowledgement, placed next to the thing that changed, and it fades once
 * it has been read. Failure does not fade — and says where the error is.
 */
export type SaveStatus = 'idle' | 'pending' | 'saving' | 'saved' | 'error';

export function SaveState({
  status,
  /** Changes on each completed save, so a second "Saved" re-shows the note. */
  savedKey,
  className = '',
}: {
  status: SaveStatus;
  savedKey?: number | string;
  className?: string;
}) {
  const [showSaved, setShowSaved] = useState(false);

  useEffect(() => {
    if (status !== 'saved') {
      setShowSaved(false);
      return;
    }
    setShowSaved(true);
    const t = window.setTimeout(() => setShowSaved(false), 2500);
    return () => window.clearTimeout(t);
  }, [status, savedKey]);

  let text = '';
  let tone = '';
  if (status === 'saving') { text = 'Saving…'; tone = 'is-busy'; }
  else if (status === 'pending') { text = 'Unsaved changes'; tone = 'is-pending'; }
  else if (status === 'error') { text = 'Not saved'; tone = 'is-error'; }
  else if (status === 'saved' && showSaved) { text = 'Saved'; tone = 'is-ok'; }

  return (
    // Always rendered so the live region exists before its first message.
    <span className={`hr-save-state ${tone} ${className}`} role="status" aria-live="polite">
      {text}
    </span>
  );
}

/**
 * `SaveStatus` for a TanStack mutation that saves on change (a select, a
 * switch): pending while in flight, saved after, error on failure.
 */
export function mutationSaveStatus(m: { isPending: boolean; isSuccess: boolean; isError: boolean }): SaveStatus {
  if (m.isPending) return 'saving';
  if (m.isError) return 'error';
  if (m.isSuccess) return 'saved';
  return 'idle';
}
