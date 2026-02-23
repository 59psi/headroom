import { apiFetch } from './client';
import type { RoomRead } from '../types';

export function listRooms() {
  return apiFetch<RoomRead[]>('/api/rooms');
}

export function getRoom(id: number) {
  return apiFetch<RoomRead>(`/api/rooms/${id}`);
}

export function createRoom(name: string) {
  return apiFetch<RoomRead>('/api/rooms', {
    method: 'POST',
    body: JSON.stringify({ name }),
  });
}

export function updateRoom(id: number, name: string) {
  return apiFetch<RoomRead>(`/api/rooms/${id}`, {
    method: 'PUT',
    body: JSON.stringify({ name }),
  });
}

export function deleteRoom(id: number) {
  return apiFetch<void>(`/api/rooms/${id}`, { method: 'DELETE' });
}

/** Room options for filter dropdowns (value/label format). */
export function getRoomOptions() {
  return apiFetch<{ value: number; label: string }[]>('/api/meta/rooms');
}
