import { apiFetch } from './client';
import type { RoomDetail, RoomRead } from '../types';

export function listRooms() {
  return apiFetch<RoomRead[]>('/api/rooms');
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

/** Move the default flag to this room, freeing the previous one for deletion. */
export function setDefaultRoom(id: number) {
  return apiFetch<RoomRead>(`/api/rooms/${id}/default`, { method: 'POST' });
}

/** Room options for filter dropdowns (value/label format). */
export function getRoomOptions() {
  return apiFetch<{ value: number; label: string }[]>('/api/meta/rooms');
}

/** A room and what is in it — loose hats first, then its cases. */
export function getRoom(id: number) {
  return apiFetch<RoomDetail>(`/api/rooms/${id}`);
}
