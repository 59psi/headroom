import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { disposeHat } from '../../api/hats';

interface Props {
  hatId: number;
  show: boolean;
  onClose: () => void;
}

const VIAS: { id: string; label: string }[] = [
  { id: 'sold', label: 'Sold' },
  { id: 'gifted', label: 'Gifted' },
  { id: 'trade', label: 'Traded' },
  { id: 'lost', label: 'Lost' },
  { id: 'trashed', label: 'Trashed' },
];

export function DisposeModal({ hatId, show, onClose }: Props) {
  const qc = useQueryClient();
  const [via, setVia] = useState('sold');
  const [price, setPrice] = useState('');
  const [to, setTo] = useState('');
  const [notes, setNotes] = useState('');

  const mut = useMutation({
    mutationFn: () => disposeHat(hatId, {
      via,
      price: price ? Number(price) : null,
      to: to.trim() || null,
      notes: notes.trim() || null,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['hat', hatId] });
      qc.invalidateQueries({ queryKey: ['hats'] });
      onClose();
    },
  });

  if (!show) return null;

  return (
    <div className="modal" onClick={onClose}>
      <div className="modal-dialog" onClick={e => e.stopPropagation()}>
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">Mark as Disposed</h5>
            <button type="button" className="btn-close" onClick={onClose} aria-label="Close" />
          </div>
          <div className="modal-body">
            <label className="form-label">Disposition Type</label>
            <select className="form-select mb-3" value={via} onChange={e => setVia(e.target.value)}>
              {VIAS.map(v => <option key={v.id} value={v.id}>{v.label}</option>)}
            </select>
            {(via === 'sold' || via === 'trade') && (
              <>
                <label className="form-label">Price ($)</label>
                <input
                  type="number"
                  step="0.01"
                  className="form-control mb-3"
                  placeholder="45.00"
                  value={price}
                  onChange={e => setPrice(e.target.value)}
                />
              </>
            )}
            <label className="form-label">{via === 'sold' || via === 'trade' ? 'Buyer / Counterparty' : 'Recipient / Where'}</label>
            <input
              type="text"
              className="form-control mb-3"
              placeholder="e.g. Eric F. or Mercari"
              value={to}
              onChange={e => setTo(e.target.value)}
            />
            <label className="form-label">Notes (optional)</label>
            <textarea
              className="form-control"
              rows={2}
              value={notes}
              onChange={e => setNotes(e.target.value)}
            />
            {mut.error && (
              <div className="alert alert-danger mt-3 mb-0 small">{String(mut.error)}</div>
            )}
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-outline-secondary" onClick={onClose}>Cancel</button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => mut.mutate()}
              disabled={mut.isPending}
            >
              {mut.isPending ? 'Saving…' : 'Mark Disposed'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
