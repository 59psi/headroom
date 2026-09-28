import { useId, useState } from 'react';
import { Modal } from './Modal';
import { ErrorNote } from './ErrorNote';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { createCase } from '../../api/cases';
import { listRooms } from '../../api/rooms';
import { invalidateHatViews } from '../../lib/invalidate';
import { useToast } from '../ui/Toast';

interface Props {
  show: boolean;
  onClose: () => void;
  onCreated: (id: number) => void;
}

export function NewCaseModal({ show, onClose, onCreated }: Props) {
  const [caseType, setCaseType] = useState('archive');
  const [roomId, setRoomId] = useState<number | ''>('');
  const qc = useQueryClient();
  const toast = useToast();
  // Before the `show` early return below: hooks run on every render.
  const formId = useId();

  const roomsQ = useQuery({ queryKey: ['rooms'], queryFn: listRooms, enabled: show });
  const rooms = roomsQ.data ?? [];
  // Never a hardcoded 1: any room can carry `is_default`, and the room that
  // does can be changed or deleted. Blank until the rooms load, then whichever
  // one is actually flagged.
  const selectedRoom = roomId !== '' ? roomId : (rooms.find(r => r.is_default)?.id ?? '');


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
        <label className="form-label" htmlFor={`${formId}-type`}>Case type</label>
        <select id={`${formId}-type`} className="form-select mb-3" value={caseType} onChange={e => setCaseType(e.target.value)}>
          <option value="archive">Archive</option>
          <option value="daily_wear">Daily wear</option>
        </select>
        <label className="form-label" htmlFor={`${formId}-room`}>Room</label>
        <select
          id={`${formId}-room`}
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
      </form>
      <ErrorNote of={[mutation, roomsQ]} className="mt-3 mb-0" />
    </Modal>
  );
}
