import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { updateHat } from '../../api/hats';
import { invalidateHatViews } from '../../lib/invalidate';
import type { HatRead } from '../../types';

/**
 * Your notes on a hat — the only free-text field a re-analysis cannot touch.
 *
 * Worth saying on screen, because every other prose field here (`design_notes`,
 * the colours, the model name) is derived and gets rewritten by a refresh. A
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
          className="form-control"
          rows={3}
          value={notes}
          placeholder="Where you got it, who you wore it with, why you kept it…"
          onChange={e => setNotes(e.target.value)}
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
          {saved && !dirty && <span className="text-muted small">Saved</span>}
          {save.isError && <span className="text-danger small">Couldn’t save — try again</span>}
        </div>
        <p className="text-muted mb-0" style={{ fontSize: '0.72rem', marginTop: 6 }}>
          Never overwritten by an analysis or a refresh.
        </p>
      </div>
    </div>
  );
}
