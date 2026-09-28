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
 *
 * The id is the row's one neon accent. The brand used to be pink as well, so
 * each row carried two competing highlights; it now reads as ordinary text
 * under the id, which is what it is.
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
  // Size is data (callers pass 64 in a room, 80 on the Hats tab), so it stays
  // inline; everything else about the thumbnail lives in the stylesheet.
  const box = { width: thumb, height: thumb };
  return (
    <Link to={`/hats/${hat.id}`} className="card hr-cp-row">
      <div className="card-body hr-cp-row-body">
        {hat.photo_path ? (
          <img src={tileSrc(hat)} alt="" className="hr-thumb hr-cp-row-thumb" style={box} />
        ) : (
          <div className="hr-cp-row-thumb hr-cp-thumb-empty" style={box} aria-hidden="true" />
        )}
        <div className="hr-cp-row-main">
          <div className="hr-cp-row-top">
            <div className="hr-cp-row-heading">
              <div className="hr-cp-row-id">{headline}</div>
              {(hat.brand || modelInSub) && (
                <div className="hr-cp-row-name">
                  {hat.brand}
                  {hat.brand && modelInSub && ' · '}
                  {modelInSub && hat.model_name}
                </div>
              )}
            </div>
            <ConditionBadge condition={hat.condition} />
          </div>
          <div className="hr-cp-row-meta">
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
