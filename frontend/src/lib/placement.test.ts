import { describe, expect, it } from 'vitest';
import { hatName, placementLabel, placementOf } from './placement';

describe('hatName', () => {
  it('prefers the shelf id, then the model, then the queue label, then the row id', () => {
    expect(hatName({ id: 5, display_id: 'A-001-02', model_name: 'Odysea Hydro' })).toBe('A-001-02');
    expect(hatName({ id: 5, display_id: null, model_name: 'Odysea Hydro' })).toBe('Odysea Hydro');
    expect(hatName({ id: 5, display_id: null, model_name: null, label: 'A-Game' })).toBe('A-Game');
    expect(hatName({ id: 5, display_id: null })).toBe('Hat #5');
  });

  it('names a report row by its hat_id, and treats a blank id as none', () => {
    expect(hatName({ hat_id: 9, display_id: null })).toBe('Hat #9');
    expect(hatName({ hat_id: 9, display_id: '' })).toBe('Hat #9');
  });
});

describe('placement', () => {
  it('tells a room-stored hat apart from an unassigned one', () => {
    expect(placementOf({ case_display_id: 'A-042', room_id: 1 })).toBe('case');
    expect(placementOf({ case_display_id: null, room_id: 2 })).toBe('room');
    expect(placementOf({ case_display_id: null, room_id: null })).toBe('none');
  });

  it('captions each state', () => {
    expect(placementLabel({ case_display_id: 'A-042', room_id: 1, room_name: 'Closet' })).toBe('A-042');
    expect(placementLabel({ case_display_id: null, room_id: 2, room_name: 'Living room' })).toBe('Living room (no case)');
    expect(placementLabel({ case_display_id: null, room_id: null, room_name: null })).toBe('Unassigned');
  });
});
