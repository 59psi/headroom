import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router';
import { getRoom } from '../api/rooms';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ConditionBadge } from '../components/common/ConditionBadge';
import { ColorSwatches } from '../components/common/ColorSwatch';
import { CaseCollage } from '../components/cases/CaseCollage';
import { tileSrc } from '../lib/photo';
import type { CaseRead, HatRead } from '../types';

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
function LooseHatRow({ hat }: { hat: HatRead }) {
  return (
    <Link to={`/hats/${hat.id}`} className="card mb-2 text-decoration-none">
      <div className="card-body d-flex gap-3 align-items-center">
        {hat.photo_path ? (
          <img src={tileSrc(hat)} alt="" className="hr-thumb flex-shrink-0" style={{ width: 64, height: 64 }} />
        ) : (
          <div
            className="rounded flex-shrink-0"
            style={{ width: 64, height: 64, background: 'rgba(0,0,0,0.3)', border: '1px dashed var(--border)' }}
          />
        )}
        <div className="flex-grow-1" style={{ minWidth: 0 }}>
          <div className="d-flex justify-content-between align-items-start gap-2">
            <div style={{ minWidth: 0 }}>
              <div className="fw-bold" style={{ color: 'var(--neon-cyan)' }}>
                {hat.model_name || `#${hat.id}`}
              </div>
              <div className="text-muted small">
                {hat.style.replace(/_/g, ' ')} · {hat.size.replace(/_/g, ' ')}
                {hat.colorway && <> · {hat.colorway}</>}
              </div>
            </div>
            <ConditionBadge condition={hat.condition} />
          </div>
          <ColorSwatches colors={hat.colors} showLabels={false} />
        </div>
      </div>
    </Link>
  );
}

function CaseCard({ c }: { c: CaseRead }) {
  const countLabel = c.beanie_count > 0
    ? `${c.beanie_count} beanie${c.beanie_count !== 1 ? 's' : ''}`
    : `${c.regular_count} hat${c.regular_count !== 1 ? 's' : ''}`;
  return (
    <Link to={`/cases/${c.display_id}`} className="card text-decoration-none h-100">
      <CaseCollage thumbs={c.hat_thumbs} label={c.display_id} />
      <div className="card-body d-flex justify-content-between align-items-center gap-2">
        <div className="font-mono fw-bold" style={{ color: 'var(--neon-cyan)' }}>{c.display_id}</div>
        <div className="font-mono small" style={{ color: 'var(--neon-pink)' }}>
          {c.hat_count === 0 ? 'Empty' : countLabel}
        </div>
      </div>
    </Link>
  );
}

export function RoomDetailPage() {
  const { roomId } = useParams();
  const id = Number(roomId);
  const { data, isLoading, error } = useQuery({
    queryKey: ['room', id],
    queryFn: () => getRoom(id),
    enabled: Number.isFinite(id),
  });

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
          {loose.map(h => <LooseHatRow key={h.id} hat={h} />)}
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
            {cases.map(c => <div className="col" key={c.id}><CaseCard c={c} /></div>)}
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
