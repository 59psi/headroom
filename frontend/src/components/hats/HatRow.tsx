import type { ReactNode } from 'react';
import { Link } from 'react-router';
import type { HatRead } from '../../types';
import { ConditionBadge } from '../common/ConditionBadge';
import { ColorSwatches } from '../common/ColorSwatch';
import { tileSrc } from '../../lib/photo';
import { useHatLabels } from '../../lib/labels';
import { hatName } from '../../lib/placement';

/**
 * What a row needs of a hat — the fields a full `HatRead` and a search result
 * both carry, so the Search page renders the same row as the Hats tab rather
 * than a copy of it. `colorway` is optional: a projection that leaves it out
 * simply shows no colorway.
 */
export type RowHat = Pick<
  HatRead,
  'id' | 'display_id' | 'model_name' | 'brand' | 'photo_path' | 'thumb_path'
  | 'condition' | 'style' | 'size' | 'room_name' | 'colors'
> & { colorway?: string | null };

/**
 * One hat as a list row: thumbnail, headline, a line of facts, its colors.
 *
 * The Hats tab, the room page and the Search page each had one (`HatRow`,
 * `LooseHatRow`, `ResultRow`), and the search copy had already drifted: it
 * called a loose hat "#12" where this row calls it by its model. Which field
 * leads is REAL and kept: a cased hat is known by its shelf id, a loose one
 * has none (`display_id` is derived from case + position), so the headline
 * falls through to the model name and then "Hat #id" — `hatName`, the rule
 * every screen shares. `showRoom` is off inside a room, where every row would
 * repeat the room you are looking at. `children` is a caller's extra line
 * under the colors — the Search page's "matched" note for a color search.
 *
 * The id is the row's one neon accent. The brand used to be pink as well, so
 * each row carried two competing highlights; it now reads as ordinary text
 * under the id, which is what it is.
 */
export function HatRow({
  hat,
  showRoom = true,
  thumb = 80,
  children,
}: {
  hat: RowHat;
  showRoom?: boolean;
  thumb?: number;
  children?: ReactNode;
}) {
  const labels = useHatLabels();
  const headline = hatName(hat);
  const modelInSub = hat.model_name && hat.model_name !== headline;
  // Size is data (callers pass 64 in a room, 72 in search results, 80 on the
  // Hats tab), so it stays inline; everything else about the thumbnail lives
  // in the stylesheet.
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
            {labels.style(hat.style)} · {labels.size(hat.size)}
            {hat.colorway && <> · {hat.colorway}</>}
            {showRoom && hat.room_name && <> · {hat.room_name}</>}
          </div>
          <ColorSwatches colors={hat.colors} showLabels={false} />
          {children}
        </div>
      </div>
    </Link>
  );
}
