import { useState, type ReactNode } from 'react';
import { isNotFound } from '../api/client';
import { ErrorNote } from '../components/common/ErrorNote';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useParams, useNavigate } from 'react-router';
import { getCase, updateCase } from '../api/cases';
import { listRooms } from '../api/rooms';
import { invalidateHatViews } from '../lib/invalidate';
import { caseTypePrefix, type CaseType } from '../lib/caseTypes';
import { qk } from '../lib/queryKeys';
import { CaseFields } from '../components/cases/CaseFields';
import { caseRoomName } from '../components/cases/CaseTile';
import { PageHeader } from '../components/ui/PageHeader';
import { Panel } from '../components/ui/Panel';
import { Skeleton } from '../components/ui/Skeleton';
import { useToast } from '../components/ui/Toast';

export function EditCasePage() {
  const { displayId } = useParams<{ displayId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();

  const caseQuery = useQuery({
    queryKey: qk.case(displayId),
    queryFn: () => getCase(displayId!),
    enabled: !!displayId,
  });

  const roomsQ = useQuery({ queryKey: qk.rooms(), queryFn: listRooms });

  // What the person has CHANGED, over the case as loaded — null means "not
  // touched, show the case's own value". Nothing is copied out of the case
  // into the form, so there is no seeding to get wrong: this query refetches
  // on window focus, and the old seed-on-every-load effect reverted a
  // half-edited form to the server's values; a room of `1` hardcoded before
  // the seed could name a room the case was never in. An edit is never
  // overwritten, and an untouched field shows the case as it now is.
  const [typeEdit, setTypeEdit] = useState<CaseType | null>(null);
  const [roomEdit, setRoomEdit] = useState<number | null>(null);
  const [capacityEdit, setCapacityEdit] = useState<string | null>(null);

  const loaded = caseQuery.data;
  const caseType = typeEdit ?? loaded?.case_type;
  const roomId = roomEdit ?? loaded?.room_id;
  const capacity = capacityEdit ?? (loaded?.capacity != null ? String(loaded.capacity) : '');

  const mutation = useMutation({
    mutationFn: () => updateCase(displayId!, {
      case_type: caseType,
      ...(roomId === undefined ? {} : { room_id: roomId }),
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

  const typeChanged = !!loaded && typeEdit !== null && typeEdit !== loaded.case_type;

  let body: ReactNode;
  if (caseQuery.isLoading) {
    body = (
      <Panel title="Case details">
        <Skeleton lines={3} label="Loading case…" />
      </Panel>
    );
  } else if (caseQuery.error && !isNotFound(caseQuery.error)) {
    body = (
      <div className="py-4">
        <ErrorNote of={caseQuery} what="Could not load this case" />
        <Link to="/cases" className="btn btn-outline-secondary mt-3">Back to cases</Link>
      </div>
    );
  } else if (!loaded || caseType === undefined || roomId === undefined) {
    // The same "not found" the case page shows, with the way out it offers —
    // this used to be a bare red box with nowhere to go.
    body = (
      <div className="hr-cr-empty mt-3">
        <p className="hr-cr-empty-title">Case not found</p>
        <p className="hr-cr-empty-text">This case may have been deleted or doesn't exist.</p>
        <Link to="/cases" className="btn btn-outline-secondary">Back to cases</Link>
      </div>
    );
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
          <CaseFields
            idPrefix="case"
            caseType={caseType}
            onCaseType={setTypeEdit}
            typeNote={typeChanged && (
              // Said BEFORE the save, because it cannot be taken back by
              // switching the type again: a case number is never issued twice
              // (`case_service.get_next_sequence`), so switching back gives a
              // new number, not the old one — and the old label finds nothing
              // rather than whichever case would otherwise have been numbered
              // next.
              <div className="alert alert-warning small mt-2 mb-0" role="note">
                Changing the type renumbers this case — {displayId} becomes the
                next {caseTypePrefix(caseType)}-### — and its hats&rsquo; IDs change with it. A
                label or NFC tag for {displayId} will stop finding it; that number is
                never reused, so it can&rsquo;t open a different case.
              </div>
            )}
            roomId={roomId}
            onRoomId={setRoomEdit}
            roomsQ={roomsQ}
            // The room the case is in now stays an option even when the list
            // lacks it — an orphaned case's room is gone.
            ownRoom={{ id: loaded.room_id, name: caseRoomName(loaded) }}
            capacity={capacity}
            onCapacity={setCapacityEdit}
            capacityHint="Leave empty to use the default for the case type."
          />
          <ErrorNote of={mutation} what="Could not save" className="mt-3" />
        </Panel>
      </form>
    );
  }

  return (
    <>
      <PageHeader back={{ to: `/cases/${displayId}`, label: displayId }} title={`Edit case ${displayId}`} />
      {body}
    </>
  );
}
