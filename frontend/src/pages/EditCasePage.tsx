import { useState, useEffect, useRef, type ReactNode } from 'react';
import { isNotFound } from '../api/client';
import { ErrorNote } from '../components/common/ErrorNote';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useParams, useNavigate } from 'react-router';
import { getCase, updateCase } from '../api/cases';
import { listRooms } from '../api/rooms';
import { CAPACITY_PLACEHOLDER } from '../lib/capacity';
import { invalidateHatViews } from '../lib/invalidate';
import { Panel } from '../components/ui/Panel';
import { Skeleton } from '../components/ui/Skeleton';
import { useToast } from '../components/ui/Toast';

export function EditCasePage() {
  const { displayId } = useParams<{ displayId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();

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
    mutationFn: () => updateCase(displayId!, {
      case_type: caseType,
      ...(roomId === '' ? {} : { room_id: roomId }),
      // An emptied box sends `null` — "back to the type default" — rather
      // than omitting the field, which the server reads as "leave it".
      capacity: capacity ? Number(capacity) : null,
    }),
    onSuccess: (updated) => {
      // This form edits `room_id`, so it MOVES a case between rooms — both
      // rooms' counts and contents change, and every hat in the case reports
      // a new `room_name`. `['case']`+`['cases']` covered none of that.
      invalidateHatViews(qc);
      const renumbered = updated.display_id !== displayId;
      toast.success(renumbered ? `Case saved as ${updated.display_id}` : 'Case saved');
      // To the id the SERVER returned, not the one in the URL. Changing the
      // type renumbers the case (`case_service.update_case`: A-001 becomes the
      // next D-###), and navigating to the old id landed on "Case not found"
      // straight after a successful save. `replace`, so Back from the case
      // does not reopen the form that was just saved.
      navigate(`/cases/${updated.display_id}`, { replace: true });
    },
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    mutation.mutate();
  }

  const loaded = caseQuery.data;
  const typeChanged = !!loaded && caseType !== '' && caseType !== loaded.case_type;
  const nextPrefix = caseType === 'archive' ? 'A' : 'D';

  let body: ReactNode;
  if (caseQuery.isLoading) {
    body = (
      <Panel title="Case details">
        <Skeleton lines={3} label="Loading case…" />
      </Panel>
    );
  } else if (caseQuery.error && !isNotFound(caseQuery.error)) {
    body = <div className="py-4"><ErrorNote of={{ isError: true, error: caseQuery.error }} what="Could not load this case" /></div>;
  } else if (!loaded) {
    body = <div className="alert alert-danger">Case not found</div>;
  } else {
    body = (
      <form onSubmit={handleSubmit} className="hr-case-form">
        <Panel
          title="Case details"
          footer={
            <>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={mutation.isPending}
              >
                {mutation.isPending ? 'Saving…' : 'Save changes'}
              </button>
              <Link to={`/cases/${displayId}`} className="btn btn-outline-secondary">Cancel</Link>
            </>
          }
        >
          <div className="hr-case-field">
            <label className="form-label" htmlFor="case-type">Case type</label>
            <select id="case-type" className="form-select" value={caseType} onChange={e => setCaseType(e.target.value)}>
              <option value="archive">Archive</option>
              <option value="daily_wear">Daily wear</option>
            </select>
            {/* Said BEFORE the save, because it cannot be taken back by
                switching the type again: the case gets the next free number
                in the other series, not its old one. */}
            {typeChanged && (
              <div className="alert alert-warning small mt-2 mb-0" role="note">
                Changing the type renumbers this case — {displayId} becomes the
                next {nextPrefix}-### — and its hats&rsquo; IDs change with it. An
                NFC tag written for {displayId} will stop finding it.
              </div>
            )}
          </div>
          <div className="hr-case-field">
            <label className="form-label" htmlFor="case-room">Room</label>
            <select id="case-room" className="form-select" value={roomId} onChange={e => setRoomId(Number(e.target.value))}>
              {roomsQ.data?.map(r => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </select>
            {/* A failed list is an empty select otherwise — no rooms to pick
                and no word why. Same note as the New case form. */}
            <ErrorNote of={roomsQ} what="Could not load rooms" />
          </div>
          <div className="hr-case-field">
            <label className="form-label" htmlFor="case-capacity">Capacity (hats)</label>
            <input
              id="case-capacity"
              type="number"
              inputMode="numeric"
              className="form-control"
              min={1}
              max={50}
              placeholder={CAPACITY_PLACEHOLDER}
              value={capacity}
              onChange={e => setCapacity(e.target.value)}
            />
            <div className="form-text">Leave empty to use the default for the case type.</div>
          </div>
          <ErrorNote of={mutation} what="Could not save" className="mt-3" />
        </Panel>
      </form>
    );
  }

  return (
    <>
      <header className="hr-cr-head">
        <div className="hr-cr-title">
          <Link to={`/cases/${displayId}`} className="hr-cr-back">{displayId}</Link>
          <h1>Edit case {displayId}</h1>
        </div>
      </header>
      {body}
    </>
  );
}
