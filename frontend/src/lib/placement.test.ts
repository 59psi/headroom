import { describe, expect, it } from 'vitest';
import { placementLabel, placementOf } from './placement';

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
