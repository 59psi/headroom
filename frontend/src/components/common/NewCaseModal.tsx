import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { createCase } from '../../api/cases';

interface Props {
  show: boolean;
  onClose: () => void;
  onCreated: (id: number) => void;
}

export function NewCaseModal({ show, onClose, onCreated }: Props) {
  const [caseType, setCaseType] = useState('archive');
  const qc = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => createCase(caseType),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['cases'] });
      onCreated(data.id);
      onClose();
    },
  });

  if (!show) return null;

  return (
    <div className="modal d-block" tabIndex={-1} style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
      <div className="modal-dialog modal-dialog-centered">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">Create New Case</h5>
            <button type="button" className="btn-close" onClick={onClose} />
          </div>
          <div className="modal-body">
            <label className="form-label">Case Type</label>
            <select className="form-select" value={caseType} onChange={e => setCaseType(e.target.value)}>
              <option value="archive">Archive</option>
              <option value="daily_wear">Daily Wear</option>
            </select>
            {mutation.error && (
              <div className="alert alert-danger mt-3 mb-0">{String(mutation.error)}</div>
            )}
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-outline-secondary" onClick={onClose}>Cancel</button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending}
            >
              {mutation.isPending ? 'Creating...' : 'Create Case'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
