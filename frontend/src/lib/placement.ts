/**
 * Where a hat lives: in a case, out in a room, or nowhere yet.
 *
 * Three states, not two. Rooms have held hats directly since 2.33 (a Caddy
 * or an Aviator fits no travel case), and `case_id == null` folded those
 * into "Unassigned" — so the Hats tab's Unassigned chip counted hats that
 * were sitting exactly where their owner put them, and the Duplicates page
 * captioned a shelf hat "Unassigned · Living room".
 *
 * Read off the two DERIVED fields both `HatRead` and `SearchResult` carry:
 * `case_display_id` is set exactly when the hat is in a case, and `room_id`
 * resolves through the case or, failing that, the hat's own room — so a
 * caseless hat with a room is a room-stored one.
 */
export type Placement = 'case' | 'room' | 'none';

export interface Placed {
  case_display_id: string | null;
  room_id: number | null;
  room_name: string | null;
}

export function placementOf(hat: Pick<Placed, 'case_display_id' | 'room_id'>): Placement {
  if (hat.case_display_id) return 'case';
  if (hat.room_id != null) return 'room';
  return 'none';
}

/** The caption for where a hat is — "A-042", "Living room (no case)" or "Unassigned". */
export function placementLabel(hat: Placed): string {
  switch (placementOf(hat)) {
    case 'case': return hat.case_display_id ?? '';
    case 'room': return `${hat.room_name ?? 'Room'} (no case)`;
    default: return 'Unassigned';
  }
}
