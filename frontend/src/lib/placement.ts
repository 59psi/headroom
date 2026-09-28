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

/**
 * What to call a hat in a list, a link or a toast.
 *
 * Its shelf id when it has one. A hat outside a case has none — `display_id`
 * is derived from case + position — so it goes by its model name, then by the
 * label the analysis queue computes, and only then by its row id, as
 * "Hat #5". Five screens each wrote their own fallback, and the same loose hat
 * was "#5", "Hat #5" or "Odysea Hydro" depending on where you met it. Takes
 * either `id` or `hat_id`, since the report rows name the hat by the latter.
 */
export type HatNameable = {
  display_id: string | null;
  model_name?: string | null;
  label?: string | null;
} & ({ id: number } | { hat_id: number });

export function hatName(h: HatNameable): string {
  const id = 'id' in h ? h.id : h.hat_id;
  return h.display_id || h.model_name || h.label || `Hat #${id}`;
}

/** The caption for where a hat is — "A-042", "Living room (no case)" or "Unassigned". */
export function placementLabel(hat: Placed): string {
  switch (placementOf(hat)) {
    case 'case': return hat.case_display_id ?? '';
    case 'room': return `${hat.room_name ?? 'Room'} (no case)`;
    default: return 'Unassigned';
  }
}
