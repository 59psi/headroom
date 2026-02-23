import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { createCase } from '../api/cases';

export function NewCasePage() {
  const [caseType, setCaseType] = useState('archive');
  const navigate = useNavigate();
  const qc = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => createCase(caseType),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['cases'] });
      navigate(`/cases/${data.display_id}`);
    },
  });

  return (
    <>
      <h1 className="mb-3">New Case</h1>

      <div className="card">
        <div className="card-body">
          <div className="mb-3">
            <label className="form-label">Case Type</label>
            <select className="form-select" value={caseType} onChange={e => setCaseType(e.target.value)}>
              <option value="archive">Archive</option>
              <option value="daily_wear">Daily Wear</option>
            </select>
          </div>

          {mutation.error && (
            <div className="alert alert-danger">{String(mutation.error)}</div>
          )}

          <button
            className="btn btn-primary w-100"
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
          >
            {mutation.isPending ? 'Creating...' : 'Create Case'}
          </button>
        </div>
      </div>
    </>
  );
}
