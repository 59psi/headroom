import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { createCase } from '../api/cases';
import { listRooms } from '../api/rooms';
import { CAPACITY_PLACEHOLDER } from '../lib/capacity';
import { invalidateHatViews } from '../lib/invalidate';

export function NewCasePage() {
  const [caseType, setCaseType] = useState('archive');
  const [roomId, setRoomId] = useState<number | ''>('');
  const [capacity, setCapacity] = useState('');
  const navigate = useNavigate();
  const qc = useQueryClient();

  const roomsQ = useQuery({ queryKey: ['rooms'], queryFn: listRooms });
  const rooms = roomsQ.data ?? [];
  // Never a hardcoded 1: any room can carry `is_default`, and the room that
  // does can be changed or deleted. Blank until the rooms load, then whichever
  // one is actually flagged.
  const selectedRoom = roomId !== '' ? roomId : (rooms.find(r => r.is_default)?.id ?? '');


  const mutation = useMutation({
    mutationFn: () => createCase(caseType, selectedRoom === '' ? null : selectedRoom, capacity ? Number(capacity) : undefined),
    onSuccess: (data) => {
      // A new case changes its room's `case_count` and the room detail page's
      // list, not just `['cases']`.
      invalidateHatViews(qc);
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
            <select aria-label="Room" className="form-select" value={selectedRoom} onChange={e => setRoomId(Number(e.target.value))}>
              {rooms.map(r => (
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
              placeholder={CAPACITY_PLACEHOLDER}
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
