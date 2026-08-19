import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { updateHat } from '../../api/hats';
import { invalidateHatViews } from '../../lib/invalidate';
import type { HatRead } from '../../types';

/**
 * The long-form write-up, plus the one field on a hat that only you write.
 *
 * `story` is derived — every analysis and every collection change rewrites it
 * — so it is shown read-only and the card says where it came from. `notes` sit
 * directly beneath precisely because the two look similar on screen and the
 * difference matters: one survives a refresh, the other does not.
 */
export function HatStoryCard({ hat }: { hat: HatRead }) {
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
    mutationFn: () => updateHat(hat.id, { owner_notes: notes.trim() || null }),
    onSuccess: () => {
      invalidateHatViews(qc, hat.id);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const dirty = notes.trim() !== (hat.owner_notes ?? '').trim();
  const paragraphs = (hat.story ?? '').split('\n').map(p => p.trim()).filter(Boolean);

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title d-flex justify-content-between align-items-center gap-2">
          <span>About this hat</span>
          {hat.story_pending && (
            <span className="badge bg-info" title="Queued for a rewrite — the collection changed">
              rewriting…
            </span>
          )}
        </div>

        {paragraphs.length > 0 ? (
          <>
            {paragraphs.map((p, i) => (
              <p key={i} className="mb-2" style={{ lineHeight: 1.6 }}>{p}</p>
            ))}
            <p className="text-muted mb-0" style={{ fontSize: '0.72rem', marginTop: 8 }}>
              {/* Said plainly because the app has no web access: this is
                  written from the photo and the facts on record, and a reader
                  should weigh it accordingly. */}
              Written by Claude from this hat's photo and recorded details
              {hat.story_generated_at
                ? ` · ${new Date(hat.story_generated_at).toLocaleDateString()}`
                : ''}
              . Rewritten whenever the hat is refreshed or its collection changes.
            </p>
          </>
        ) : (
          <p className="text-secondary mb-0" style={{ fontSize: '0.9rem' }}>
            {hat.story_pending
              ? 'A write-up is queued for this hat.'
              : 'No write-up yet — set this hat’s collection, or refresh it, to have one written.'}
          </p>
        )}

        <hr style={{ borderColor: 'var(--border)', margin: '1rem 0 0.75rem' }} />

        <label htmlFor={`notes-${hat.id}`} className="form-label" style={{ fontSize: '0.8rem' }}>
          Your notes
        </label>
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
