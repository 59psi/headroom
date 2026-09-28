import type { ReactNode } from 'react';
import type { UseQueryResult } from '@tanstack/react-query';
import { ErrorNote } from '../common/ErrorNote';
import { CAPACITY_PLACEHOLDER } from '../../lib/capacity';
import { CASE_TYPES, type CaseType, isCaseType } from '../../lib/caseTypes';
import type { RoomRead } from '../../types';

/** A room a case can be put in — an id and the name to show for it. */
export interface RoomChoice {
  id: number;
  name: string;
}

/**
 * The rooms a case's picker offers, with the case's OWN room first when the
 * list does not contain it.
 *
 * Two situations leave the list without it: the list has not arrived yet, and
 * a case orphaned by an older version (`update_case` names editing it as the
 * repair) whose room is gone. With no option matching its value, a select
 * displays its first option while meaning none — the case appeared to be in
 * the first room, and choosing that room fired no change, so the one room it
 * could not be moved to was the one it seemed to be in. The case detail page
 * handled this; the Edit form, a copy of the same select, did not.
 */
export function roomChoices(rooms: readonly RoomRead[] | undefined, own?: RoomChoice | null): RoomChoice[] {
  const list = rooms ?? [];
  if (!own || list.some(r => r.id === own.id)) return [...list];
  return [own, ...list];
}

/**
 * The room a NEW case goes to: the one picked, else whichever room carries
 * `is_default`, else nothing until the rooms load.
 *
 * Never a hardcoded 1: any room can hold the flag, and the room that does can
 * be changed or deleted.
 */
export function defaultRoomId(rooms: readonly RoomRead[] | undefined, picked: number | ''): number | '' {
  if (picked !== '') return picked;
  return rooms?.find(r => r.is_default)?.id ?? '';
}

/**
 * A case's type, room and capacity — the fields the New case page and the
 * Edit case page both render.
 *
 * They were two copies of the same markup that had already drifted: the Edit
 * copy had no "Loading rooms…" option and showed an orphaned case in the
 * wrong room. `capacity` is optional so a form without it (the quick
 * New case dialog) can use the same type and room fields.
 */
export function CaseFields({
  idPrefix,
  caseType,
  onCaseType,
  typeNote,
  roomId,
  onRoomId,
  roomsQ,
  ownRoom,
  capacity,
  onCapacity,
  capacityHint,
}: {
  /** Prefix for the controls' ids, unique on the page. */
  idPrefix: string;
  caseType: CaseType;
  onCaseType: (next: CaseType) => void;
  /** Said under the type select — the renumber warning on the Edit form. */
  typeNote?: ReactNode;
  roomId: number | '';
  onRoomId: (next: number) => void;
  roomsQ: Pick<UseQueryResult<RoomRead[]>, 'data' | 'isLoading' | 'isError' | 'error'>;
  /** The room the case is in now, kept as an option even when the list lacks it. */
  ownRoom?: RoomChoice | null;
  capacity?: string;
  onCapacity?: (next: string) => void;
  capacityHint?: ReactNode;
}) {
  const rooms = roomChoices(roomsQ.data, ownRoom);
  return (
    <>
      <div className="hr-case-field">
        <label className="form-label" htmlFor={`${idPrefix}-type`}>Case type</label>
        <select
          id={`${idPrefix}-type`}
          className="form-select"
          value={caseType}
          onChange={e => { if (isCaseType(e.target.value)) onCaseType(e.target.value); }}
        >
          {CASE_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
        {typeNote}
      </div>

      <div className="hr-case-field">
        <label className="form-label" htmlFor={`${idPrefix}-room`}>Room</label>
        <select
          id={`${idPrefix}-room`}
          className="form-select"
          value={roomId}
          disabled={roomsQ.isLoading && !ownRoom}
          onChange={e => onRoomId(Number(e.target.value))}
        >
          {roomsQ.isLoading && !ownRoom && <option value="">Loading rooms…</option>}
          {rooms.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>
        {/* A failed list is an empty select otherwise — no rooms to pick and
            no word why. */}
        <ErrorNote of={roomsQ} what="Could not load rooms" />
      </div>

      {onCapacity && (
        <div className="hr-case-field">
          <label className="form-label" htmlFor={`${idPrefix}-capacity`}>Capacity (hats)</label>
          <input
            id={`${idPrefix}-capacity`}
            type="number"
            inputMode="numeric"
            className="form-control"
            min={1}
            max={50}
            placeholder={CAPACITY_PLACEHOLDER}
            value={capacity ?? ''}
            onChange={e => onCapacity(e.target.value)}
          />
          {capacityHint && <div className="form-text">{capacityHint}</div>}
        </div>
      )}
    </>
  );
}
