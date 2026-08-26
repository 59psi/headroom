import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { updateHat } from '../../api/hats';
import { invalidateHatViews } from '../../lib/invalidate';
import type { HatRead } from '../../types';

/**
 * Your notes on a hat — the only free-text field a re-analysis cannot touch.
 *
 * Worth saying on screen, because every other prose field here (`design_notes`,
 * the colors, the model name) is derived and gets rewritten by a refresh. A
 * field that looks the same and behaves differently is a trap unless it says
 * which one it is.
 */
export function HatNotesCard({ hat }: { hat: HatRead }) {
  const qc = useQueryClient();
  const [notes, setNotes] = useState(hat.owner_notes ?? '');
  const [saved, setSaved] = useState(false);

  // Reset when the page swaps to a DIFFERENT hat. Keyed on the id, not on the
  // notes: following `owner_notes` would overwrite whatever is being typed
  // every time a refetch lands, and the only thing that changes it server-side
  // is this component's own save.
  useEffect(() => {
    setNotes(hat.owner_notes ?? '');
  }, [hat.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    // null, not '' — an empty string reads as "has notes, which are blank",
    // and renders and exports differently from a hat that never had any.
    mutationFn: () => updateHat(hat.id, { owner_notes: notes.trim() || null }),
    onSuccess: () => {
      invalidateHatViews(qc, hat.id);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const dirty = notes.trim() !== (hat.owner_notes ?? '').trim();

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Your notes</div>
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
          // Enter inserts a newline in a textarea, so the usual submit gesture
          // is unavailable — which on a field with a separate Save button
          // means typing a note and navigating away silently loses it.
          onKeyDown={e => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && dirty && !save.isPending) {
              e.preventDefault();
              save.mutate();
            }
          }}
        />
        <div className="d-flex align-items-center gap-2" style={{ marginTop: 8 }}>
          <button
            type="button"
            className="btn btn-outline-primary btn-sm"
            disabled={!dirty || save.isPending}
            onClick={() => save.mutate()}
          >
            {save.isPending ? 'Saving…' : 'Save notes'}
          </button>
          {/* Unsaved beats Saved: this field has its own button rather than
              saving with the rest of the form, so "you have typed something
              that is not stored yet" is the state worth showing. */}
          {dirty && !save.isPending && <span className="text-muted small">Unsaved changes</span>}
          {saved && !dirty && <span className="text-muted small">Saved</span>}
          {save.isError && <span className="text-danger small">Couldn’t save — try again</span>}
        </div>
        <p className="text-muted mb-0" style={{ fontSize: '0.72rem', marginTop: 6 }}>
          Never overwritten by an analysis or a refresh.{' '}
          {/* Hidden on touch: neither key is on an iPhone or iPad soft
              keyboard, and this app is phone-first, so on the primary device
              this sentence was instructions for hardware you don't have. */}
          <span className="hr-keyboard-hint">
            Press <kbd>⌘</kbd>/<kbd>Ctrl</kbd> + <kbd>Enter</kbd> to save.
          </span>
        </p>
      </div>
    </div>
  );
}
