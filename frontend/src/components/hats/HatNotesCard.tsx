import { useCallback, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { updateHat } from '../../api/hats';
import { invalidateHatViews } from '../../lib/invalidate';
import { useAutosave } from '../../lib/useAutosave';
import { Panel } from '../ui/Panel';
import { SaveState } from '../ui/SaveState';
import { ErrorNote } from '../common/ErrorNote';
import type { HatRead } from '../../types';

/** Whitespace at the ends is not an edit — the save trims it anyway. */
const sameNotes = (a: string, b: string) => a.trim() === b.trim();

/**
 * Your notes on a hat — the only free-text field a re-analysis cannot touch.
 *
 * Worth saying on screen, because every other prose field here (`design_notes`,
 * the colors, the model name) is derived and gets rewritten by a refresh. A
 * field that looks the same and behaves differently is a trap unless it says
 * which one it is.
 *
 * Saves itself. It had a Save button, which on a phone meant typing a note
 * and tapping Back lost it — the one field that is entirely yours was the
 * one that could vanish. Now it saves shortly after typing stops, on blur,
 * immediately on ⌘/Ctrl+Enter, and on the way out of the page (`useAutosave`
 * flushes on unmount), with a "Saving… / Saved" note in the card's header.
 */
export function HatNotesCard({ hat }: { hat: HatRead }) {
  const qc = useQueryClient();
  const [notes, setNotes] = useState(hat.owner_notes ?? '');

  // No reset effect. `HatDetailPage` mounts this as `<HatNotesCard key={data.id}>`,
  // so swapping to a different hat is a fresh instance and `hat.id` can never
  // change inside one; the `useState` seed above is the reset — and it is
  // also the autosave's baseline, which is why the page renders this only
  // once the hat has loaded. (The draft is deliberately NOT re-synced from
  // `owner_notes` on refetch — that would overwrite whatever is being typed,
  // and the only thing that changes it server-side is this component's own
  // save.)

  const save = useCallback(async (value: string) => {
    // null, not '' — an empty string reads as "has notes, which are blank",
    // and renders and exports differently from a hat that never had any.
    await updateHat(hat.id, { owner_notes: value.trim() || null });
    // Not awaited: "Saved" is about the write, not the lists refetching.
    void invalidateHatViews(qc, hat.id);
  }, [hat.id, qc]);

  const { status, error, flush, savedCount } = useAutosave(notes, save, { isEqual: sameNotes });

  return (
    <Panel
      title="Notes"
      description="Never overwritten by an analysis or a refresh — saves as you type."
      status={<SaveState status={status} savedKey={savedCount} />}
    >
      <textarea
        id={`notes-${hat.id}`}
        aria-label="Your notes"
        className="form-control hr-notes-input"
        // The floor for browsers without `field-sizing`. Deliberately NOT
        // claimed to equal the CSS min-height: that is a border-box value
        // under the global `box-sizing`, so it works out a couple of pixels
        // short of five rows — and per MDN `rows` has no effect at all once
        // `field-sizing: content` applies, so the two never both decide.
        rows={5}
        value={notes}
        placeholder="Where you got it, who you wore it with, why you kept it…"
        onChange={e => setNotes(e.target.value)}
        // Leaving the field is the natural "done" — save then rather than
        // waiting out the debounce, so a tap on a link right after typing
        // does not race it.
        onBlur={() => { void flush(); }}
        // Enter inserts a newline in a textarea, so the usual submit gesture
        // is unavailable; ⌘/Ctrl+Enter is the keyboard's "save now".
        onKeyDown={e => {
          if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
            e.preventDefault();
            void flush();
          }
        }}
      />
      {/* Hidden on touch: neither key is on an iPhone or iPad soft keyboard,
          and this app is phone-first, so on the primary device this sentence
          was instructions for hardware you don't have. */}
      <p className="hr-notes-hint hr-keyboard-hint">
        <kbd>⌘</kbd>/<kbd>Ctrl</kbd> + <kbd>Enter</kbd> saves now.
      </p>
      {status === 'error' && (
        <div className="hr-notes-error">
          <ErrorNote of={{ isError: true, error }} what="Notes not saved" className="" />
          <button type="button" className="btn btn-outline-secondary btn-sm" onClick={() => { void flush(); }}>
            Try again
          </button>
        </div>
      )}
    </Panel>
  );
}
