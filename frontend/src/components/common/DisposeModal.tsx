import { useId, useState } from 'react';
import { Modal } from './Modal';
import { ErrorNote } from './ErrorNote';
import { ChoiceGroup } from './ColorScopePicker';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { disposeHat } from '../../api/hats';
import { invalidateHatViews } from '../../lib/invalidate';
import { useToast } from '../ui/Toast';

interface Props {
  hatId: number;
  show: boolean;
  onClose: () => void;
}

/** How a hat can leave the collection: the stored value and the word shown. */
export const DISPOSITIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: 'sold', label: 'Sold' },
  { value: 'gifted', label: 'Gifted' },
  { value: 'trade', label: 'Traded' },
  { value: 'lost', label: 'Lost' },
  { value: 'trashed', label: 'Trashed' },
];

/**
 * The word for a stored `disposed_via`. The hat page used to print the raw
 * value upper-cased ("TRADE on 3/4/2026"), which is the column, not the
 * English — the list above already had the word.
 */
export function dispositionLabel(via: string | null | undefined): string {
  const known = DISPOSITIONS.find(d => d.value === via)?.label;
  if (known) return known;
  return via ? via.charAt(0).toUpperCase() + via.slice(1) : 'Disposed';
}

export function DisposeModal({ hatId, show, onClose }: Props) {
  const qc = useQueryClient();
  const toast = useToast();
  const [via, setVia] = useState('sold');
  const [price, setPrice] = useState('');
  const [to, setTo] = useState('');
  const [notes, setNotes] = useState('');
  const viaLabelId = useId();

  const viaWord = dispositionLabel(via).toLowerCase();
  const hasPrice = via === 'sold' || via === 'trade';

  const mut = useMutation({
    mutationFn: () => disposeHat(hatId, {
      via,
      // Only the kinds that HAVE a price send one. The field is hidden for the
      // others, but its state survives switching back and forth — a price
      // typed under "Sold" must not ride along on a "Gifted".
      price: hasPrice && price ? Number(price) : null,
      to: to.trim() || null,
      notes: notes.trim() || null,
    }),
    onSuccess: () => {
      invalidateHatViews(qc, hatId);
      toast.success(`Marked as ${viaWord}`);
      onClose();
    },
  });

  if (!show) return null;

  return (
    <Modal title="Mark as disposed" onClose={onClose}
      footer={(
        <>
          <button type="button" className="btn btn-outline-secondary" onClick={onClose}>Cancel</button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => mut.mutate()}
            disabled={mut.isPending}
          >
            {mut.isPending ? 'Saving…' : `Mark as ${viaWord}`}
          </button>
        </>
      )}
    >
      <p className="text-secondary small mb-3">
        Soft-delete only: the hat keeps its record, frees its case slot, and
        can be restored from its page.
      </p>

      {/* Chips, not a <select>: five short words that fit on screen at once
          were two taps and an iOS picker wheel away. */}
      <span className="form-label" id={viaLabelId}>What happened</span>
      <div className="mb-3">
        <ChoiceGroup
          variant="chips"
          labelledBy={viaLabelId}
          options={DISPOSITIONS}
          value={via}
          onChange={setVia}
        />
      </div>
      {hasPrice && (
        <>
          <label className="form-label" htmlFor="dispose-price">Price ($)</label>
          <input
            id="dispose-price"
            type="number"
            inputMode="decimal"
            step="0.01"
            min="0"
            className="form-control mb-3"
            placeholder="45.00"
            value={price}
            onChange={e => setPrice(e.target.value)}
          />
        </>
      )}
      <label className="form-label" htmlFor="dispose-to">{hasPrice ? 'Buyer or counterparty' : 'Recipient or place'}</label>
      <input
        id="dispose-to"
        type="text"
        className="form-control mb-3"
        placeholder="e.g. Eric F. or Mercari"
        value={to}
        onChange={e => setTo(e.target.value)}
      />
      <label className="form-label" htmlFor="dispose-notes">Notes (optional)</label>
      <textarea
        id="dispose-notes"
        className="form-control"
        rows={3}
        value={notes}
        onChange={e => setNotes(e.target.value)}
      />
      <ErrorNote of={mut} className="mt-3 mb-0 small" />
    </Modal>
  );
}
