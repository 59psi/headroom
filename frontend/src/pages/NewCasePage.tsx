import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router';
import { createCase } from '../api/cases';
import { listRooms } from '../api/rooms';
import { CAPACITY_PLACEHOLDER, DEFAULT_REGULAR_CAPACITY } from '../lib/capacity';
import { invalidateHatViews } from '../lib/invalidate';
import { ErrorNote } from '../components/common/ErrorNote';
import { PageHeader } from '../components/ui/PageHeader';
import { Panel } from '../components/ui/Panel';
import { useToast } from '../components/ui/Toast';

export function NewCasePage() {
  const [caseType, setCaseType] = useState('archive');
  const [roomId, setRoomId] = useState<number | ''>('');
  const [capacity, setCapacity] = useState('');
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();

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
      toast.success(`Case ${data.display_id} created`);
      // `replace`: Back from the new case goes to wherever "New case" was
      // tapped, not to this form, blank again, inviting a second case.
      navigate(`/cases/${data.display_id}`, { replace: true });
    },
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!mutation.isPending) mutation.mutate();
  }

  return (
    <>
      <PageHeader back={{ to: '/cases', label: 'Cases' }} title="New case" />

      <form onSubmit={handleSubmit} className="hr-case-form">
        <Panel
          title="Case details"
          // `case_service._make_display_id`: the prefix is the type, the
          // number the next in that series.
          description="Cases are numbered in order: A-### for archive, D-### for daily wear."
          footer={
            <>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={mutation.isPending}
              >
                {mutation.isPending ? 'Creating…' : 'Create case'}
              </button>
              <Link to="/cases" className="btn btn-outline-secondary">Cancel</Link>
            </>
          }
        >
          <div className="hr-case-field">
            <label className="form-label" htmlFor="new-case-type">Case type</label>
            <select id="new-case-type" className="form-select" value={caseType} onChange={e => setCaseType(e.target.value)}>
              <option value="archive">Archive</option>
              <option value="daily_wear">Daily wear</option>
            </select>
          </div>

          <div className="hr-case-field">
            <label className="form-label" htmlFor="new-case-room">Room</label>
            <select
              id="new-case-room"
              className="form-select"
              value={selectedRoom}
              disabled={roomsQ.isLoading}
              onChange={e => setRoomId(Number(e.target.value))}
            >
              {roomsQ.isLoading && <option value="">Loading rooms…</option>}
              {rooms.map(r => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </select>
            <ErrorNote of={roomsQ} what="Could not load rooms" />
          </div>

          <div className="hr-case-field">
            <label className="form-label" htmlFor="new-case-capacity">Capacity (hats)</label>
            <input
              id="new-case-capacity"
              type="number"
              inputMode="numeric"
              className="form-control"
              min={1}
              max={50}
              placeholder={CAPACITY_PLACEHOLDER}
              value={capacity}
              onChange={e => setCapacity(e.target.value)}
            />
            <div className="form-text">
              e.g. {DEFAULT_REGULAR_CAPACITY} for a Melin case that fits {DEFAULT_REGULAR_CAPACITY} hats comfortably
            </div>
          </div>

          <ErrorNote of={mutation} what="Could not create the case" className="mt-3" />
        </Panel>
      </form>
    </>
  );
}
