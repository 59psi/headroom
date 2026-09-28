import { useQuery } from '@tanstack/react-query';
import { isNotFound } from '../api/client';
import { ErrorNote } from '../components/common/ErrorNote';
import { Link, useParams } from 'react-router';
import { getRoom } from '../api/rooms';
import { CaseGridSkeleton, CaseTile } from '../components/cases/CaseTile';
import { HatRow } from '../components/hats/HatRow';
import { PageHeader } from '../components/ui/PageHeader';
import { StatusPill } from '../components/ui/StatusPill';

/**
 * What is actually in a room.
 *
 * There was no room view at all until now — `/rooms` listed names with edit
 * and delete buttons, and rooms weren't clickable. So the room-stored hats
 * added in 2.33 had nowhere to be seen: the Cases tab reaches a hat through
 * its case, and a hat on a shelf has no case to be reached through.
 *
 * **Loose hats come first**, above the cases, for that reason. A cased hat is
 * findable three other ways; a loose one is findable here and in search. It is
 * also the truthful order for a physical room — the things sitting out are
 * what you see when you walk in.
 *
 * The two lists are page SECTIONS (a heading over a run of cards), not
 * `Panel`s: every item in them is already a card, and a card of cards is one
 * border too many.
 */
export function RoomDetailPage() {
  const { roomId } = useParams();
  const id = Number(roomId);
  const { data, isLoading, error } = useQuery({
    queryKey: ['room', id],
    queryFn: () => getRoom(id),
    enabled: Number.isFinite(id),
  });

  if (error && !isNotFound(error)) {
    return (
      <div className="py-4">
        <ErrorNote of={{ isError: true, error }} what="Could not load this room" />
        <Link to="/rooms" className="btn btn-outline-secondary mt-3">← All rooms</Link>
      </div>
    );
  }
  if (!Number.isFinite(id) || error) {
    return (
      <div className="hr-cr-empty mt-3">
        <p className="hr-cr-empty-title">Room not found</p>
        <Link to="/rooms" className="btn btn-outline-secondary">← All rooms</Link>
      </div>
    );
  }
  if (isLoading || !data) {
    return (
      <>
        {/* The way back works before the room arrives; the grid below is
            the one "Loading room…" announcement. */}
        <PageHeader back={{ to: '/rooms', label: 'Rooms' }} loading />
        <CaseGridSkeleton count={4} label="Loading room…" />
      </>
    );
  }

  const loose = data.loose_hats ?? [];
  const cases = data.cases ?? [];
  const summary = [
    `${cases.length} case${cases.length === 1 ? '' : 's'}`,
    loose.length > 0 && `${loose.length} loose hat${loose.length === 1 ? '' : 's'}`,
  ].filter(Boolean).join(' · ');

  return (
    <>
      <PageHeader
        back={{ to: '/rooms', label: 'Rooms' }}
        title={data.name}
        summary={
          <>
            <span>{summary}</span>
            {data.is_default && <StatusPill tone="info">Default</StatusPill>}
          </>
        }
      />

      {/* Out on the shelf, first. See the module docstring. */}
      {loose.length > 0 && (
        <section className="hr-cr-section" aria-labelledby="room-loose-title">
          <div className="hr-cr-section-head">
            <h2 id="room-loose-title">Out in this room</h2>
            <span className="hr-cr-section-count">
              {loose.length} hat{loose.length === 1 ? '' : 's'}, no case
            </span>
          </div>
          {loose.map(h => <HatRow key={h.id} hat={h} showRoom={false} thumb={64} />)}
        </section>
      )}

      <section className="hr-cr-section" aria-labelledby="room-cases-title">
        <div className="hr-cr-section-head">
          <h2 id="room-cases-title">Cases</h2>
          <span className="hr-cr-section-count">
            {cases.length} case{cases.length === 1 ? '' : 's'}
          </span>
        </div>
        {cases.length === 0 ? (
          <p className="hr-cr-note">
            No cases in this room{loose.length > 0 ? '.' : ' yet.'}
          </p>
        ) : (
          <div className="hr-case-grid">
            {cases.map(c => <CaseTile key={c.id} c={c} showRoom={false} />)}
          </div>
        )}
      </section>

      {loose.length === 0 && cases.length === 0 && (
        <p className="hr-cr-note">
          This room is empty. Hats can be kept here without a case — a Caddy or
          an Aviator doesn't fit a travel case at all.
        </p>
      )}
    </>
  );
}
