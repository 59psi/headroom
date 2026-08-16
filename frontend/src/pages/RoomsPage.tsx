import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router';
import { listRooms, createRoom, updateRoom, deleteRoom, setDefaultRoom } from '../api/rooms';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import type { RoomRead } from '../types';

function RoomCard({ room, onEdit, onDelete, onMakeDefault }: {
  room: RoomRead;
  onEdit: (id: number, name: string) => void;
  onDelete: (id: number) => void;
  onMakeDefault: (id: number) => void;
}) {
  return (
    <div className="card mb-2">
      <div className="card-body d-flex justify-content-between align-items-center gap-2 flex-wrap">
        <div>
          <div className="fw-bold fs-5 d-flex align-items-center gap-2" style={{ color: 'var(--text)' }}>
            {room.name}
            {room.is_default && (
              <span className="badge" style={{
                background: 'rgba(0,240,255,0.15)', color: 'var(--neon-cyan)',
                fontSize: '0.65rem', textTransform: 'uppercase', letterSpacing: '0.06em',
              }}>Default</span>
            )}
          </div>
          <div className="text-muted small font-mono">
            {room.case_count} case{room.case_count !== 1 ? 's' : ''}
          </div>
        </div>
        <div className="d-flex gap-1">
          {!room.is_default && (
            <button
              className="btn btn-sm btn-outline-primary"
              title="Make this the room new cases go to, and where cases land when their room is deleted"
              onClick={() => onMakeDefault(room.id)}
            >Make default</button>
          )}
          <button className="btn btn-sm btn-outline-secondary" onClick={() => onEdit(room.id, room.name)}>Rename</button>
          <button
            className="btn btn-sm btn-outline-danger"
            disabled={room.is_default}
            title={room.is_default
              ? 'The default room cannot be deleted — make another room the default first'
              : 'Delete room'}
            onClick={() => onDelete(room.id)}
          >Delete</button>
        </div>
      </div>
    </div>
  );
}

export function RoomsPage() {
  const qc = useQueryClient();
  const [newRoomName, setNewRoomName] = useState('');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState('');

  const roomsQ = useQuery({ queryKey: ['rooms'], queryFn: listRooms });

  const createMut = useMutation({
    mutationFn: () => createRoom(newRoomName.trim()),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['rooms'] });
      qc.invalidateQueries({ queryKey: ['meta', 'rooms'] });
      setNewRoomName('');
    },
  });

  const updateMut = useMutation({
    mutationFn: (vars: { id: number; name: string }) => updateRoom(vars.id, vars.name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['rooms'] });
      qc.invalidateQueries({ queryKey: ['meta', 'rooms'] });
      qc.invalidateQueries({ queryKey: ['cases'] });
      setEditingId(null);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteRoom(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['rooms'] });
      qc.invalidateQueries({ queryKey: ['meta', 'rooms'] });
      qc.invalidateQueries({ queryKey: ['cases'] });
    },
  });

  const defaultMut = useMutation({
    mutationFn: (id: number) => setDefaultRoom(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['rooms'] });
      qc.invalidateQueries({ queryKey: ['meta', 'rooms'] });
    },
  });

  function handleEdit(id: number, name: string) {
    setEditingId(id);
    setEditName(name);
  }

  function handleDelete(id: number) {
    const room = roomsQ.data?.find(r => r.id === id);
    if (!room) return;
    // Name the actual destination — it's whichever room holds the flag, which
    // is no longer necessarily one called "Default Room".
    const defaultRoomName = roomsQ.data?.find(r => r.is_default)?.name ?? 'the default room';
    const msg = room.case_count > 0
      ? `Delete "${room.name}"? Its ${room.case_count} case(s) will move to ${defaultRoomName}.`
      : `Delete "${room.name}"?`;
    if (confirm(msg)) deleteMut.mutate(id);
  }

  function saveEdit() {
    if (editingId && editName.trim()) {
      updateMut.mutate({ id: editingId, name: editName.trim() });
    }
  }

  if (roomsQ.isLoading) return <LoadingSpinner />;
  if (roomsQ.error) return (
    <div className="text-center py-5">
      <h5 className="mb-2">Could not load rooms</h5>
      <Link to="/" className="btn btn-outline-primary">← Back</Link>
    </div>
  );

  const anyError = createMut.error || updateMut.error || deleteMut.error || defaultMut.error;

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
        <h1>Rooms</h1>
      </div>

      <p className="text-secondary small mb-3">
        Rooms organize where your cases are stored. Each case belongs to one room.
        One room is the <strong>default</strong>: new cases go there, and cases land
        there when their room is deleted. It's the only room that can't be deleted —
        make another room the default first to free it up.
      </p>

      {editingId && (
        <div className="card mb-3 border-primary">
          <div className="card-body">
            <label className="form-label">Rename Room</label>
            <div className="d-flex gap-2 flex-wrap">
              <input
                type="text"
                className="form-control flex-grow-1"
                style={{ minWidth: 200 }}
                value={editName}
                onChange={e => setEditName(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') saveEdit(); if (e.key === 'Escape') setEditingId(null); }}
                autoFocus
              />
              <button className="btn btn-primary" onClick={saveEdit} disabled={updateMut.isPending}>
                {updateMut.isPending ? 'Saving…' : 'Save'}
              </button>
              <button className="btn btn-outline-secondary" onClick={() => setEditingId(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {roomsQ.data?.map(r => (
        <RoomCard
          key={r.id}
          room={r}
          onEdit={handleEdit}
          onDelete={handleDelete}
          onMakeDefault={id => defaultMut.mutate(id)}
        />
      ))}

      <div className="card mt-3">
        <div className="card-body">
          <label className="form-label">Add Room</label>
          <div className="d-flex gap-2 flex-wrap">
            <input
              type="text"
              className="form-control flex-grow-1"
              style={{ minWidth: 200 }}
              placeholder="Room name"
              value={newRoomName}
              onChange={e => setNewRoomName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && newRoomName.trim()) createMut.mutate(); }}
            />
            <button
              className="btn btn-primary"
              disabled={!newRoomName.trim() || createMut.isPending}
              onClick={() => createMut.mutate()}
            >
              {createMut.isPending ? 'Adding…' : 'Add Room'}
            </button>
          </div>
        </div>
      </div>

      {anyError && (
        <div className="alert alert-danger mt-3">{String(anyError)}</div>
      )}
    </>
  );
}
