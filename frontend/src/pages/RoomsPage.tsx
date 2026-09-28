import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useQuery, useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { Link } from 'react-router';
import { listRooms, createRoom, updateRoom, deleteRoom, setDefaultRoom } from '../api/rooms';
import { invalidateHatViews } from '../lib/invalidate';
import { ErrorNote } from '../components/common/ErrorNote';
import { Panel } from '../components/ui/Panel';
import { StatusPill } from '../components/ui/StatusPill';
import { Skeleton } from '../components/ui/Skeleton';
import { useConfirm } from '../components/ui/Dialogs';
import { useToast } from '../components/ui/Toast';
import type { RoomRead } from '../types';

const ROOMS_KEY = ['rooms'] as const;

/** Server-side names are capped here (`schemas/common.RoomName`). */
const ROOM_NAME_MAX = 100;

type Failing = { isError: boolean; error: unknown };

function plural(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}

/**
 * Same order as `room_service.list_rooms` (`ORDER BY name`, SQLite's default
 * BINARY collation — a plain code-unit compare, so "Zed" sorts before
 * "attic"). A room added or renamed in place lands where the refetch will
 * put it, instead of appearing at the end and then jumping.
 */
function byName(a: RoomRead, b: RoomRead) {
  return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
}

/**
 * Snapshot the room list and apply `change` to it at once; the mutation's
 * `onError` puts the snapshot back. Every room mutation here has a result the
 * page can predict — the row renamed, gone, or holding the default flag — so
 * the list shows it the moment the button is pressed, and only a failure
 * changes it again.
 */
async function applyOptimistic(qc: QueryClient, change: (rooms: RoomRead[]) => RoomRead[]) {
  // A refetch already in flight would land after this and overwrite it with
  // the pre-change list.
  await qc.cancelQueries({ queryKey: ROOMS_KEY });
  const prev = qc.getQueryData<RoomRead[]>(ROOMS_KEY);
  if (prev) qc.setQueryData<RoomRead[]>(ROOMS_KEY, change(prev));
  return { prev };
}

function rollback(qc: QueryClient, ctx: { prev?: RoomRead[] } | undefined) {
  if (ctx?.prev) qc.setQueryData(ROOMS_KEY, ctx.prev);
}

/**
 * The row whose rename field is open. `draft` is set only when the field was
 * REOPENED by a failed save: it holds what was typed, so the retry is one
 * press of Enter rather than typing the name again.
 */
type Editing = { id: number; draft?: string };

function RenameForm({ room, draft, onSave, onCancel }: {
  room: RoomRead;
  draft?: string;
  onSave: (name: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(draft ?? room.name);
  const inputRef = useRef<HTMLInputElement>(null);
  const trimmed = value.trim();
  // Focus with the old name SELECTED, so typing replaces it and an arrow key
  // edits it — the rename field in every file manager. A field reopened by a
  // failed save arrives while the person may be typing somewhere else (the
  // save is optimistic, so they were free to move on), so it takes focus only
  // if nothing else holds it — which is also the case when it replaces the
  // row's own Rename button, the element focus was on.
  useEffect(() => {
    const active = document.activeElement;
    if (draft !== undefined && active && active !== document.body) return;
    inputRef.current?.focus();
    inputRef.current?.select();
    // Mount only: a reopened field is a fresh mount (see `Editing`).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <form
      className="hr-field-row hr-room-rename"
      onSubmit={e => {
        e.preventDefault();
        if (trimmed) onSave(trimmed);
      }}
    >
      <label className="visually-hidden" htmlFor={`rename-room-${room.id}`}>
        New name for {room.name}
      </label>
      <input
        id={`rename-room-${room.id}`}
        ref={inputRef}
        type="text"
        className="form-control"
        value={value}
        maxLength={ROOM_NAME_MAX}
        enterKeyHint="done"
        autoComplete="off"
        onChange={e => setValue(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Escape') {
            e.preventDefault();
            onCancel();
          }
        }}
      />
      <button type="submit" className="btn btn-outline-primary" disabled={!trimmed}>Save</button>
      <button type="button" className="btn btn-outline-secondary" onClick={onCancel}>Cancel</button>
    </form>
  );
}

function RoomRow({ room, editing, draft, onStartRename, onRename, onCancelRename, onMakeDefault, onDelete, errors }: {
  room: RoomRead;
  editing: boolean;
  draft?: string;
  onStartRename: () => void;
  onRename: (name: string) => void;
  onCancelRename: () => void;
  onMakeDefault: () => void;
  onDelete: () => void;
  errors: { of: Failing; what: string }[];
}) {
  const renameBtn = useRef<HTMLButtonElement>(null);
  // When the rename field closes (saved or canceled) focus would otherwise
  // drop to <body>, and a keyboard user starts the page over from the top.
  // Only when nothing else has taken it — tapping "Rename" on ANOTHER row
  // also closes this one, and focus belongs over there.
  const wasEditing = useRef(editing);
  useEffect(() => {
    if (wasEditing.current && !editing) {
      const active = document.activeElement;
      if (!active || active === document.body) renameBtn.current?.focus();
    }
    wasEditing.current = editing;
  }, [editing]);

  const failed = errors.find(e => e.of.isError);

  return (
    <li className={`hr-room-row${editing ? ' is-editing' : ''}`}>
      {editing ? (
        <RenameForm room={room} draft={draft} onSave={onRename} onCancel={onCancelRename} />
      ) : (
        <>
          <Link to={`/rooms/${room.id}`} className="hr-room-main">
            <span className="hr-room-name">{room.name}</span>
            {room.is_default && <StatusPill tone="info">Default</StatusPill>}
            <span className="hr-room-meta">
              {plural(room.case_count, 'case')}
              {/* A room holding only loose hats used to read as empty. */}
              {room.loose_hat_count > 0 && <> · {room.loose_hat_count} loose</>}
            </span>
            <span className="hr-cr-chevron" aria-hidden="true" />
          </Link>
          {/* The SAME three buttons on every row, disabled where they don't
              apply rather than hidden. Hiding "Make default" on the default
              room while Delete was only disabled gave rows different numbers
              of buttons — so some wrapped to a second line and others didn't,
              and the list re-flowed whenever the default moved. The visible
              word names the action; the hidden room name tells a screen
              reader, hearing "Delete" in a list of rows, which one. The space
              sits OUTSIDE the hidden span: name computation trims each
              element's text, so " Study" inside it read as "DeleteStudy". */}
          <div className="hr-room-actions">
            <button
              type="button"
              className="btn btn-sm btn-outline-secondary"
              disabled={room.is_default}
              title={room.is_default
                ? 'This is already the default room'
                : 'Make this the room new cases go to, and where cases land when their room is deleted'}
              onClick={onMakeDefault}
            >Make default<span className="visually-hidden">: {room.name}</span></button>
            <button
              type="button"
              ref={renameBtn}
              className="btn btn-sm btn-outline-secondary"
              onClick={onStartRename}
            >Rename{' '}<span className="visually-hidden">{room.name}</span></button>
            <button
              type="button"
              className="btn btn-sm btn-outline-danger"
              disabled={room.is_default}
              title={room.is_default
                ? 'The default room cannot be deleted — make another room the default first'
                : 'Delete room'}
              onClick={onDelete}
            >Delete{' '}<span className="visually-hidden">{room.name}</span></button>
          </div>
        </>
      )}
      {failed && <ErrorNote of={failed.of} what={failed.what} className="" />}
    </li>
  );
}

export function RoomsPage() {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const toast = useToast();
  const [newRoomName, setNewRoomName] = useState('');
  const [editing, setEditing] = useState<Editing | null>(null);

  const roomsQ = useQuery({ queryKey: ROOMS_KEY, queryFn: listRooms });

  const createMut = useMutation({
    mutationFn: (name: string) => createRoom(name),
    onSuccess: (room) => {
      // Into the list from the server's own answer, so the row is there the
      // moment the request returns rather than after a second round trip; the
      // refetch in `onSettled` then confirms it.
      qc.setQueryData<RoomRead[]>(ROOMS_KEY, old => (old ? [...old, room].sort(byName) : old));
      setNewRoomName('');
      toast.success(`Added “${room.name}”`);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ROOMS_KEY });
      qc.invalidateQueries({ queryKey: ['meta', 'rooms'] });
    },
  });

  // Renaming a room changes the `room_name` printed on every hat card and
  // every case row; deleting one MOVES its cases and its loose hats to the
  // default room. Both were invalidating `['rooms']`/`['cases']` only, so the
  // hat lists kept showing the old name — or the deleted room — for the whole
  // 30s staleTime.
  const renameMut = useMutation({
    mutationFn: (vars: { id: number; name: string }) => updateRoom(vars.id, vars.name),
    onMutate: ({ id, name }) => {
      setEditing(null);
      return applyOptimistic(qc, rooms => rooms.map(r => (r.id === id ? { ...r, name } : r)).sort(byName));
    },
    onError: (_err, { id, name }, ctx) => {
      rollback(qc, ctx);
      // The field closed the moment Save was pressed, taking the typed name
      // with it. Reopen it holding that name, with the reason under it — the
      // separate rename card this replaced simply stayed open on a failure.
      // Not over a field the person has since opened on another row.
      setEditing(cur => cur ?? { id, draft: name });
    },
    onSuccess: (room) => toast.success(`Renamed to “${room.name}”`),
    onSettled: () => {
      invalidateHatViews(qc);
      qc.invalidateQueries({ queryKey: ['meta', 'rooms'] });
    },
  });

  const deleteMut = useMutation({
    mutationFn: (vars: { id: number; name: string }) => deleteRoom(vars.id),
    onMutate: ({ id }) => applyOptimistic(qc, rooms => rooms.filter(r => r.id !== id)),
    onError: (_err, _vars, ctx) => rollback(qc, ctx),
    onSuccess: (_void, { name }) => toast.success(`Deleted “${name}”`),
    onSettled: () => {
      invalidateHatViews(qc);
      qc.invalidateQueries({ queryKey: ['meta', 'rooms'] });
    },
  });

  // Exactly one room holds the flag, so moving it is predictable: this row
  // gains it, every other row loses it.
  const defaultMut = useMutation({
    mutationFn: (id: number) => setDefaultRoom(id),
    onMutate: id => applyOptimistic(qc, rooms => rooms.map(r => ({ ...r, is_default: r.id === id }))),
    onError: (_err, _id, ctx) => rollback(qc, ctx),
    onSuccess: (room) => toast.success(`“${room.name}” is now the default room`),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ROOMS_KEY });
      qc.invalidateQueries({ queryKey: ['meta', 'rooms'] });
    },
  });

  function handleRename(room: RoomRead, name: string) {
    // Unchanged: close the field without a request or a "Renamed" toast.
    if (name === room.name) {
      setEditing(null);
      return;
    }
    renameMut.mutate({ id: room.id, name });
  }

  async function handleDelete(room: RoomRead) {
    const rooms = roomsQ.data ?? [];
    // Name the actual destination — it's whichever room holds the flag, which
    // is no longer necessarily one called "Default Room".
    const defaultRoomName = rooms.find(r => r.is_default)?.name ?? 'the default room';
    // Loose hats move too — `delete_room` sweeps `direct_room_id` as well as
    // the cases — and they are the contents you can ONLY see from this room,
    // so leaving them out of the warning understated what the button does.
    const moving = [
      room.case_count > 0 && plural(room.case_count, 'case'),
      room.loose_hat_count > 0 && plural(room.loose_hat_count, 'loose hat'),
    ].filter(Boolean).join(' and ');
    const ok = await confirm({
      title: `Delete “${room.name}”?`,
      // No body when nothing moves: the dialog's own "This can't be undone."
      body: moving ? `Its ${moving} will move to ${defaultRoomName}.` : undefined,
      confirmLabel: 'Delete room',
      tone: 'danger',
    });
    if (ok) deleteMut.mutate({ id: room.id, name: room.name });
  }

  function addRoom() {
    const name = newRoomName.trim();
    if (name && !createMut.isPending) createMut.mutate(name);
  }

  // Each row shows the failure of an action taken ON IT, under it — one
  // alert at the foot of the page used to report a failed rename of the
  // first room below the last one.
  function rowErrors(id: number) {
    return [
      { of: rowFailure(renameMut, renameMut.variables?.id === id), what: 'Could not rename' },
      { of: rowFailure(deleteMut, deleteMut.variables?.id === id), what: 'Could not delete' },
      { of: rowFailure(defaultMut, defaultMut.variables === id), what: 'Could not make this the default' },
    ];
  }

  const rooms = roomsQ.data;
  const caseTotal = rooms?.reduce((n, r) => n + r.case_count, 0) ?? 0;

  let body: ReactNode;
  if (roomsQ.isLoading) {
    body = <Skeleton lines={4} label="Loading rooms…" />;
  } else if (roomsQ.error || !rooms) {
    body = (
      <>
        <ErrorNote of={{ isError: true, error: roomsQ.error }} what="Could not load rooms" className="" />
        <Link to="/" className="btn btn-outline-secondary btn-sm mt-3">Back</Link>
      </>
    );
  } else {
    body = (
      <ul className="hr-room-list">
        {rooms.map(r => (
          <RoomRow
            key={r.id}
            room={r}
            editing={editing?.id === r.id}
            draft={editing?.id === r.id ? editing.draft : undefined}
            onStartRename={() => setEditing({ id: r.id })}
            onRename={name => handleRename(r, name)}
            onCancelRename={() => setEditing(null)}
            onMakeDefault={() => defaultMut.mutate(r.id)}
            onDelete={() => { void handleDelete(r); }}
            errors={rowErrors(r.id)}
          />
        ))}
      </ul>
    );
  }

  return (
    <>
      <header className="hr-cr-head">
        <div className="hr-cr-title">
          <h1>Rooms</h1>
          {rooms && (
            <p className="hr-cr-sub">{plural(rooms.length, 'room')} · {plural(caseTotal, 'case')}</p>
          )}
        </div>
      </header>

      <Panel
        title="Your rooms"
        description="Rooms organize where your cases are stored. Each case belongs to one room."
        helpLabel="About the default room"
        help={
          <p>
            One room is the <strong>default</strong>: new cases go there, and cases land
            there when their room is deleted. It&rsquo;s the only room that can&rsquo;t be deleted —
            make another room the default first to free it up.
          </p>
        }
        footer={rooms && (
          <div className="hr-room-add">
            <form
              className="hr-field-row"
              onSubmit={e => { e.preventDefault(); addRoom(); }}
            >
              <label className="visually-hidden" htmlFor="add-room">Add room</label>
              <input
                id="add-room"
                type="text"
                className="form-control"
                placeholder="New room name"
                maxLength={ROOM_NAME_MAX}
                enterKeyHint="done"
                autoComplete="off"
                value={newRoomName}
                onChange={e => setNewRoomName(e.target.value)}
              />
              <button
                type="submit"
                className="btn btn-primary"
                disabled={!newRoomName.trim() || createMut.isPending}
              >
                {createMut.isPending ? 'Adding…' : 'Add room'}
              </button>
            </form>
            <ErrorNote of={createMut} what="Could not add the room" />
          </div>
        )}
      >
        {body}
      </Panel>
    </>
  );
}

/** A mutation's failure, but only when it was about this row. */
function rowFailure(m: Failing, isThisRow: boolean): Failing {
  return { isError: m.isError && isThisRow, error: m.error };
}
