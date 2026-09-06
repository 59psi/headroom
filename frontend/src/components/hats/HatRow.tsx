import { Link } from 'react-router';
import type { HatRead } from '../../types';
import { ConditionBadge } from '../common/ConditionBadge';
import { ColorSwatches } from '../common/ColorSwatch';
import { tileSrc } from '../../lib/photo';

/**
 * One hat as a list row: thumbnail, headline, a line of facts, its colors.
 *
 * The Hats tab and the room page each had one (`HatRow` / `LooseHatRow`),
 * differing in which field led. That difference is REAL and kept: a cased hat
 * is known by its shelf id, a loose one has none (`display_id` is derived
 * from case + position), so the headline falls through to the model name and
 * then the row id. `showRoom` is off inside a room, where every row would
 * repeat the room you are looking at.
 */
export function HatRow({
  hat,
  showRoom = true,
  thumb = 80,
}: {
  hat: HatRead;
  showRoom?: boolean;
  thumb?: number;
}) {
  const headline = hat.display_id || hat.model_name || `#${hat.id}`;
  const modelInSub = hat.model_name && hat.model_name !== headline;
  return (
    <Link to={`/hats/${hat.id}`} className="card mb-2 text-decoration-none">
      <div className="card-body d-flex gap-3 align-items-center">
        {hat.photo_path ? (
          <img src={tileSrc(hat)} alt="" className="hr-thumb flex-shrink-0" style={{ width: thumb, height: thumb }} />
        ) : (
          <div
            className="rounded flex-shrink-0"
            style={{ width: thumb, height: thumb, background: 'rgba(0,0,0,0.3)', border: '1px dashed var(--border)' }}
          />
        )}
        <div className="flex-grow-1" style={{ minWidth: 0 }}>
          <div className="d-flex justify-content-between align-items-start gap-2">
            <div style={{ minWidth: 0 }}>
              <div className="fw-bold font-mono" style={{ color: 'var(--neon-cyan)' }}>{headline}</div>
              {(hat.brand || modelInSub) && (
                <div className="text-secondary small">
                  {hat.brand && <span style={{ color: 'var(--neon-pink)' }}>{hat.brand}</span>}
                  {hat.brand && modelInSub && ' · '}
                  {modelInSub && hat.model_name}
                </div>
              )}
            </div>
            <ConditionBadge condition={hat.condition} />
          </div>
          <div className="text-muted small mb-1" style={{ marginTop: 4 }}>
            {hat.style.replace(/_/g, ' ')} · {hat.size.replace(/_/g, ' ')}
            {hat.colorway && <> · {hat.colorway}</>}
            {showRoom && hat.room_name && <> · {hat.room_name}</>}
          </div>
          <ColorSwatches colors={hat.colors} showLabels={false} />
        </div>
      </div>
    </Link>
  );
}
