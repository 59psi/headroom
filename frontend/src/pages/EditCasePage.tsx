import { useState, useEffect, useRef } from 'react';
import { isNotFound } from '../api/client';
import { ErrorNote } from '../components/common/ErrorNote';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router';
import { getCase, updateCase } from '../api/cases';
import { listRooms } from '../api/rooms';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { CAPACITY_PLACEHOLDER } from '../lib/capacity';
import { invalidateHatViews } from '../lib/invalidate';

export function EditCasePage() {
  const { displayId } = useParams<{ displayId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const caseQuery = useQuery({
    queryKey: ['case', displayId],
    queryFn: () => getCase(displayId!),
    enabled: !!displayId,
  });

  const roomsQ = useQuery({ queryKey: ['rooms'], queryFn: listRooms });

  const [caseType, setCaseType] = useState('');
  // No room until the case says which — a hardcoded `1` was the seed room's
  // id on a fresh install and some other room's on any install that had
  // deleted it, so the select could name a room the case was never in.
  const [roomId, setRoomId] = useState<number | ''>('');
  const [capacity, setCapacity] = useState('');

  // Seed the form ONCE per case, not on every refetch — the same rule the
  // Edit-hat page follows. This query refetches on window focus, and re-running
  // the seed then reverted a half-edited form to the server's values.
  const seededFor = useRef<string | null>(null);
  useEffect(() => {
    if (!caseQuery.data || seededFor.current === caseQuery.data.display_id) return;
    seededFor.current = caseQuery.data.display_id;
    setCaseType(caseQuery.data.case_type);
    setRoomId(caseQuery.data.room_id);
    setCapacity(caseQuery.data.capacity != null ? String(caseQuery.data.capacity) : '');
  }, [caseQuery.data]);

  const mutation = useMutation({
    mutationFn: async () => {
      await updateCase(displayId!, {
        case_type: caseType,
        ...(roomId === '' ? {} : { room_id: roomId }),
        // An emptied box sends `null` — "back to the type default" — rather
        // than omitting the field, which the server reads as "leave it".
        capacity: capacity ? Number(capacity) : null,
      });
    },
    onSuccess: () => {
      // This form edits `room_id`, so it MOVES a case between rooms — both
      // rooms' counts and contents change, and every hat in the case reports
      // a new `room_name`. `['case']`+`['cases']` covered none of that.
      invalidateHatViews(qc);
      navigate(`/cases/${displayId}`);
    },
  });


  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    mutation.mutate();
  }

  if (caseQuery.isLoading) return <LoadingSpinner />;
  if (caseQuery.error && !isNotFound(caseQuery.error)) {
    return <div className="py-4"><ErrorNote of={{ isError: true, error: caseQuery.error }} what="Could not load this case" /></div>;
  }
  if (!caseQuery.data) return <div className="alert alert-danger">Case not found</div>;

  return (
    <>
      <h1 className="mb-3">Edit Case {displayId}</h1>

      <form onSubmit={handleSubmit}>
        <div className="card mb-3">
          <div className="card-body">
            <div className="mb-3">
              <label className="form-label" htmlFor="case-type">Case Type</label>
              <select id="case-type" className="form-select" value={caseType} onChange={e => setCaseType(e.target.value)}>
                <option value="archive">Archive</option>
                <option value="daily_wear">Daily Wear</option>
              </select>
            </div>
            <div className="mb-3">
              <label className="form-label" htmlFor="case-room">Room</label>
              <select id="case-room" className="form-select" value={roomId} onChange={e => setRoomId(Number(e.target.value))}>
                {roomsQ.data?.map(r => (
                  <option key={r.id} value={r.id}>{r.name}</option>
                ))}
              </select>
            </div>
            <div className="mb-3">
              <label className="form-label" htmlFor="case-capacity">Capacity (hats)</label>
              <input
                id="case-capacity"
                type="number"
                className="form-control"
                min={1}
                max={50}
                placeholder={CAPACITY_PLACEHOLDER}
                value={capacity}
                onChange={e => setCapacity(e.target.value)}
              />
            </div>
          </div>
        </div>

        {mutation.error && (
          <div className="alert alert-danger">{String(mutation.error)}</div>
        )}

        <button
          type="submit"
          className="btn btn-primary w-100 btn-lg"
          disabled={mutation.isPending}
        >
          {mutation.isPending ? 'Saving…' : 'Save Changes'}
        </button>
      </form>
    </>
  );
}
