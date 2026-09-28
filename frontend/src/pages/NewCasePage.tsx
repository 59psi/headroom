import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router';
import { createCase } from '../api/cases';
import { listRooms } from '../api/rooms';
import { DEFAULT_REGULAR_CAPACITY } from '../lib/capacity';
import { CASE_TYPES, type CaseType } from '../lib/caseTypes';
import { invalidateHatViews } from '../lib/invalidate';
import { qk } from '../lib/queryKeys';
import { CaseFields, defaultRoomId } from '../components/cases/CaseFields';
import { ErrorNote } from '../components/common/ErrorNote';
import { PageHeader } from '../components/ui/PageHeader';
import { Panel } from '../components/ui/Panel';
import { useToast } from '../components/ui/Toast';

export function NewCasePage() {
  const [caseType, setCaseType] = useState<CaseType>('archive');
  const [roomId, setRoomId] = useState<number | ''>('');
  const [capacity, setCapacity] = useState('');
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();

  const roomsQ = useQuery({ queryKey: qk.rooms(), queryFn: listRooms });
  const selectedRoom = defaultRoomId(roomsQ.data, roomId);

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
          description={`Cases are numbered in order: ${CASE_TYPES
            .map(t => `${t.prefix}-### for ${t.label.toLowerCase()}`).join(', ')}.`}
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
          <CaseFields
            idPrefix="new-case"
            caseType={caseType}
            onCaseType={setCaseType}
            roomId={selectedRoom}
            onRoomId={setRoomId}
            roomsQ={roomsQ}
            capacity={capacity}
            onCapacity={setCapacity}
            capacityHint={`e.g. ${DEFAULT_REGULAR_CAPACITY} for a Melin case that fits ${DEFAULT_REGULAR_CAPACITY} hats comfortably`}
          />

          <ErrorNote of={mutation} what="Could not create the case" className="mt-3" />
        </Panel>
      </form>
    </>
  );
}
