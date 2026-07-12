import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { createCase } from '../api/cases';
import { listRooms } from '../api/rooms';

export function NewCasePage() {
  const [caseType, setCaseType] = useState('archive');
  const [roomId, setRoomId] = useState(1);
  const [capacity, setCapacity] = useState('');
  const navigate = useNavigate();
  const qc = useQueryClient();

  const roomsQ = useQuery({ queryKey: ['rooms'], queryFn: listRooms });

  const mutation = useMutation({
    mutationFn: () => createCase(caseType, roomId, capacity ? Number(capacity) : undefined),
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

          <div className="mb-3">
            <label className="form-label">Room</label>
            <select className="form-select" value={roomId} onChange={e => setRoomId(Number(e.target.value))}>
              {roomsQ.data?.map(r => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </select>
          </div>

          <div className="mb-3">
            <label className="form-label">Capacity (hats)</label>
            <input
              type="number"
              className="form-control"
              min={1}
              max={50}
              placeholder="Default: 4 regular / 6 beanies"
              value={capacity}
              onChange={e => setCapacity(e.target.value)}
            />
            <div className="form-text small">e.g. 3 for a Melin case that fits 3 hats comfortably</div>
          </div>

          {mutation.error && (
            <div className="alert alert-danger">{String(mutation.error)}</div>
          )}

          <button
            className="btn btn-primary w-100"
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
          >
            {mutation.isPending ? 'Creating…' : 'Create Case'}
          </button>
        </div>
      </div>
    </>
  );
}
