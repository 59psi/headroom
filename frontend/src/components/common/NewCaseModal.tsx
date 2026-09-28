import { useId, useState } from 'react';
import { Modal } from './Modal';
import { ErrorNote } from './ErrorNote';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { createCase } from '../../api/cases';
import { listRooms } from '../../api/rooms';
import type { CaseType } from '../../lib/caseTypes';
import { invalidateHatViews } from '../../lib/invalidate';
import { qk } from '../../lib/queryKeys';
import { CaseFields, defaultRoomId } from '../cases/CaseFields';
import { useToast } from '../ui/Toast';

interface Props {
  show: boolean;
  onClose: () => void;
  onCreated: (id: number) => void;
}

export function NewCaseModal({ show, onClose, onCreated }: Props) {
  const [caseType, setCaseType] = useState<CaseType>('archive');
  const [roomId, setRoomId] = useState<number | ''>('');
  const qc = useQueryClient();
  const toast = useToast();
  // Before the `show` early return below: hooks run on every render.
  const formId = useId();

  const roomsQ = useQuery({ queryKey: qk.rooms(), queryFn: listRooms, enabled: show });
  // The New case page's rule, from the same helper: the room picked, else the
  // one flagged default — never a hardcoded 1.
  const selectedRoom = defaultRoomId(roomsQ.data, roomId);

  const mutation = useMutation({
    mutationFn: async () => {
      const data = await createCase(caseType, selectedRoom === '' ? null : selectedRoom);
      // Same reach as the full page: a new case changes its room's counts and
      // contents too.
      await invalidateHatViews(qc);
      return data;
    },
    onSuccess: (data) => {
      // The hat form behind the modal only shows the picker switching to the
      // new case; the toast names the number it was given.
      toast.success(`Case ${data.display_id} created`);
      onCreated(data.id);
      onClose();
    },
  });

  if (!show) return null;

  return (
    <Modal title="New case" onClose={onClose}
      footer={(
        <>
          <button type="button" className="btn btn-outline-secondary" onClick={onClose}>Cancel</button>
          <button
            type="submit"
            form={formId}
            className="btn btn-primary"
            disabled={mutation.isPending}
          >
            {mutation.isPending ? 'Creating…' : 'Create case'}
          </button>
        </>
      )}
    >
      {/* A real form, submitted by the footer's button through `form=`, so
          the create has one entry point and one double-submit guard. Not an
          Enter-to-submit form: browsers submit implicitly only from a text
          field, and this dialog has none — two selects. */}
      <form id={formId} onSubmit={e => { e.preventDefault(); if (!mutation.isPending) mutation.mutate(); }}>
        {/* The New case page's own fields (`CaseFields`), less the capacity
            this quick dialog does not ask for — so the three case forms
            cannot disagree on what a type is called, which room a new case
            starts in, or how a failed room list is reported (it says so
            under the room picker). */}
        <CaseFields
          idPrefix={formId}
          caseType={caseType}
          onCaseType={setCaseType}
          roomId={selectedRoom}
          onRoomId={setRoomId}
          roomsQ={roomsQ}
        />
      </form>
      <ErrorNote of={mutation} className="mt-3 mb-0" />
    </Modal>
  );
}
