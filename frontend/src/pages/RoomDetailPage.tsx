import { useQuery } from '@tanstack/react-query';
import { isNotFound } from '../api/client';
import { ErrorNote } from '../components/common/ErrorNote';
import { Link, useParams } from 'react-router';
import { getRoom } from '../api/rooms';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { CaseTile } from '../components/cases/CaseTile';
import { HatRow } from '../components/hats/HatRow';

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
        <Link to="/rooms" className="btn btn-outline-primary mt-3">← All rooms</Link>
      </div>
    );
  }
  if (!Number.isFinite(id) || error) {
    return (
      <div className="text-center py-5">
        <h5 className="mb-2">Room not found</h5>
        <Link to="/rooms" className="btn btn-outline-primary">← All rooms</Link>
      </div>
    );
  }
  if (isLoading || !data) return <LoadingSpinner />;

  const loose = data.loose_hats ?? [];
  const cases = data.cases ?? [];

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3 gap-2 flex-wrap">
        <h1 className="mb-0">{data.name}</h1>
        <Link to="/rooms" className="btn btn-outline-secondary btn-sm">← Rooms</Link>
      </div>

      {/* Out on the shelf, first. See the module docstring. */}
      {loose.length > 0 && (
        <section className="mb-4">
          <div className="d-flex justify-content-between align-items-baseline mb-2">
            <h2 className="h6 mb-0">Out in this room</h2>
            <span className="text-secondary small">
              {loose.length} hat{loose.length === 1 ? '' : 's'}, no case
            </span>
          </div>
          {loose.map(h => <HatRow key={h.id} hat={h} showRoom={false} thumb={64} />)}
        </section>
      )}

      <section>
        <div className="d-flex justify-content-between align-items-baseline mb-2">
          <h2 className="h6 mb-0">Cases</h2>
          <span className="text-secondary small">
            {cases.length} case{cases.length === 1 ? '' : 's'}
          </span>
        </div>
        {cases.length === 0 ? (
          <p className="text-secondary small">
            No cases in this room{loose.length > 0 ? '.' : ' yet.'}
          </p>
        ) : (
          <div className="row row-cols-2 row-cols-md-3 g-3">
            {cases.map(c => <div className="col" key={c.id}><CaseTile c={c} showRoom={false} /></div>)}
          </div>
        )}
      </section>

      {loose.length === 0 && cases.length === 0 && (
        <p className="text-secondary small mt-3">
          This room is empty. Hats can be kept here without a case — a Caddy or
          an Aviator doesn't fit a travel case at all.
        </p>
      )}
    </>
  );
}
