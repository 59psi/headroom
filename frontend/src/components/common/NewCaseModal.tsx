import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { createCase } from '../../api/cases';
import { listRooms } from '../../api/rooms';

interface Props {
  show: boolean;
  onClose: () => void;
  onCreated: (id: number) => void;
}

export function NewCaseModal({ show, onClose, onCreated }: Props) {
  const [caseType, setCaseType] = useState('archive');
  const [roomId, setRoomId] = useState(1);
  const qc = useQueryClient();

  const roomsQ = useQuery({ queryKey: ['rooms'], queryFn: listRooms, enabled: show });

  const mutation = useMutation({
    mutationFn: async () => {
      const data = await createCase(caseType, roomId);
      await qc.invalidateQueries({ queryKey: ['cases'] });
      return data;
    },
    onSuccess: (data) => {
      onCreated(data.id);
      onClose();
    },
  });

  if (!show) return null;

  return (
    <div className="modal" onClick={onClose}>
      <div className="modal-dialog" onClick={e => e.stopPropagation()}>
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">Create New Case</h5>
            <button type="button" className="btn-close" onClick={onClose} aria-label="Close" />
          </div>
          <div className="modal-body">
            <label className="form-label">Case Type</label>
            <select className="form-select mb-3" value={caseType} onChange={e => setCaseType(e.target.value)}>
              <option value="archive">Archive</option>
              <option value="daily_wear">Daily Wear</option>
            </select>
            <label className="form-label">Room</label>
            <select className="form-select" value={roomId} onChange={e => setRoomId(Number(e.target.value))}>
              {roomsQ.data?.map(r => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </select>
            {mutation.error && (
              <div className="alert alert-danger mt-3 mb-0">{String(mutation.error)}</div>
            )}
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-outline-secondary" onClick={onClose}>Cancel</button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending}
            >
              {mutation.isPending ? 'Creating…' : 'Create Case'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
