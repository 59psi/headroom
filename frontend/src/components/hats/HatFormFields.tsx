import { useState, useRef, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getStyles, getSizes, getConditions, getConstructions, getCollections } from '../../api/hats';
import { listCases } from '../../api/cases';
import { PhotoCapture } from '../photos/PhotoCapture';
import { Combobox } from '../common/Combobox';
import { CasePicker } from './CasePicker';

/** The fields the Add and Edit hat forms share verbatim. */
export interface HatBasics {
  style: string;
  size: string;
  condition: string;
  /**
   * Construction ('' = not stated), orthogonal to style so any model can be
   * any of them. Known builds are offered as autocomplete options from
   * `GET /api/meta/constructions`; anything else typed is stored verbatim.
   */
  construction: string;
  /** Collection / collaboration name ('' = not stated). */
  artistSeries: string;
  /** Case id as a string ('' = unassigned), matching the <select> value. */
  caseId: string;
  /** ISO date or '' */
  dateLastWorn: string;
  /** What was paid, as typed ('' = not stated). Kept as a string so the input
   *  stays controlled while it's mid-edit — a `number|null` field turns "12."
   *  into NaN on the keystroke before the cents. */
  purchasePrice: string;
  /** ISO date the hat was bought, or '' */
  purchasedAt: string;
}

// Defined by the picker that uses it; re-exported so existing importers of
// this module keep working.
export { NEW_CASE_VALUE } from './CasePicker';

/**
 * Pre-selection for any form that creates hats (Add Hat, Bulk Import).
 *
 * Mirrors `HAT_DEFAULTS` in `src/headroom/schemas/hat.py`, which is what the
 * server applies when a request omits these. Kept in one place per side rather
 * than restated per page — `tests/test_import.py` pins the server half so the
 * three backend entry points can't drift from each other.
 */
// Widened to `string` on purpose: `as const` would infer literal types and make
// these unusable as useState seeds for controls whose value is a plain string.
export const DEFAULT_HAT_BASICS: {
  style: string; size: string; condition: string; construction: string; artistSeries: string;
} = {
  style: 'a_game',
  size: 'classic',
  condition: 'new',
  construction: '',
  artistSeries: '',
};

/** The dropdown sources both hat forms need, plus a single loading flag. */
export function useHatFormOptions() {
  const styles = useQuery({ queryKey: ['meta', 'styles'], queryFn: getStyles });
  const sizes = useQuery({ queryKey: ['meta', 'sizes'], queryFn: getSizes });
  const conditions = useQuery({ queryKey: ['meta', 'conditions'], queryFn: getConditions });
  const constructions = useQuery({ queryKey: ['meta', 'constructions'], queryFn: getConstructions });
  const collections = useQuery({ queryKey: ['meta', 'collections'], queryFn: getCollections });
  const cases = useQuery({ queryKey: ['cases'], queryFn: listCases });

  return {
    styles, sizes, conditions, constructions, collections, cases,
    // `constructions` is deliberately absent from `isLoading`: it only fills
    // the suggestion list, so a slow or failed fetch costs autocomplete, not
    // the ability to type a value.
    isLoading: styles.isLoading || sizes.isLoading || conditions.isLoading,
  };
}

/** Selected-file + object-URL preview pair, used identically by both forms. */
export function useHatPhoto() {
  const [photo, setPhoto] = useState<File | null>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  // Only ever holds a URL we minted. `setPhotoPreview` is also called with a
  // server path (`/uploads/…`) by the Edit page, and revoking one of those
  // would be meaningless — so track ours separately rather than revoking
  // whatever happens to be in `photoPreview`.
  const objectUrl = useRef<string | null>(null);

  function onCapture(file: File) {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    const url = URL.createObjectURL(file);
    objectUrl.current = url;
    setPhoto(file);
    setPhotoPreview(url);
  }

  // Without this each retaken photo pinned a full-resolution camera image in
  // memory for the lifetime of the SPA.
  useEffect(() => () => {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
  }, []);

  return { photo, photoPreview, setPhotoPreview, onCapture };
}

export function PhotoCard({ onCapture, previewUrl }: {
  onCapture: (file: File) => void;
  previewUrl: string | null;
}) {
  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Photo</div>
        <PhotoCapture onCapture={onCapture} previewUrl={previewUrl} />
      </div>
    </div>
  );
}

interface BasicsCardProps {
  values: HatBasics;
  onChange: <K extends keyof HatBasics>(key: K, value: HatBasics[K]) => void;
  options: ReturnType<typeof useHatFormOptions>;
  /** Invoked when the user picks "+ Create New Case…". */
  onCreateCase: () => void;
  caseLabel?: string;
  dateLabel?: string;
}

/** Style / Size / Condition / Case / Date Last Worn — identical on both forms. */
export function HatBasicsCard({
  values, onChange, options, onCreateCase,
  caseLabel = 'Case Assignment',
  dateLabel = 'Date Last Worn',
}: BasicsCardProps) {
  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Details</div>

        <div className="mb-3">
          <label className="form-label">Style</label>
          <select aria-label="Style" className="form-select" value={values.style} onChange={e => onChange('style', e.target.value)}>
            {options.styles.data?.map(s => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </div>

        <div className="mb-3">
          <label className="form-label">Size</label>
          <select aria-label="Size" className="form-select" value={values.size} onChange={e => onChange('size', e.target.value)}>
            {options.sizes.data?.map(s => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </div>

        <div className="mb-3">
          <label className="form-label">Condition</label>
          <select aria-label="Condition" className="form-select" value={values.condition} onChange={e => onChange('condition', e.target.value)}>
            {options.conditions.data?.map(c => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
        </div>

        {/* Beside Style rather than inside it: these are constructions melin
            offers ACROSS models, so a hat is "a Coronado, in HYDROLite", never
            "a HYDROLite instead of a Coronado".

            A combobox and not a <select>: melin ships specialty fabrics in
            seasonal and collab drops, so any closed list is wrong by next
            season. The known builds are visible, tappable rows that filter as
            you type, and anything else you type is still accepted. The options
            come from the server, which merges the curated list with every
            value already in use — so a fabric typed once is a suggestion after
            that, and the free-form half doesn't fill up with five spellings of
            the same material. */}
        <div className="mb-3">
          <Combobox
            id="hat-construction"
            label="Construction"
            value={values.construction}
            onChange={v => onChange('construction', v)}
            options={options.constructions.data ?? []}
            placeholder="HYDRO, HYDROLite, Thermal…"
            help={
              <>Tap a known build or type the fabric. Leave blank if it's a
              standard one — analysis fills it in when it can identify the hat.</>
            }
          />
        </div>

        {/* Editable at ADD time, not only on the Edit form. A collection or
            collaboration name is printed on the box and the hang tag, and is
            frequently invisible in a photo of the hat itself — so the owner
            standing there with it knows something the analyser cannot see, and
            making them save first and edit second meant either a second trip
            or hoping Claude guessed. Analysis leaves a filled-in value alone. */}
        <div className="mb-3">
          <Combobox
            id="hat-artist-series"
            label="Collection or collaboration"
            value={values.artistSeries}
            onChange={v => onChange('artistSeries', v)}
            options={options.collections.data ?? []}
            placeholder="Piña, Skye Walker, melin x OluKai…"
            help={
              <>Signature collaborations, artist series and named collections.
              Pick an existing one to keep them from splitting into
              &ldquo;Neon&rdquo;, &ldquo;NEON&rdquo; and &ldquo;neon&rdquo; —
              and if you type one anyway, it snaps to the spelling already on
              record. Analysis fills this in when it recognises one; anything
              you type survives a re-analysis.</>
            }
          />
        </div>

        <div className="mb-3">
          <CasePicker
            label={caseLabel}
            value={values.caseId}
            onChange={v => onChange('caseId', v)}
            cases={options.cases.data ?? []}
            // Which cases can take this hat depends on what it IS — a beanie
            // and a regular hat see different availability in the same case.
            isBeanie={
              options.styles.data?.find(o => o.value === values.style)?.is_beanie ?? false
            }
            onCreateCase={onCreateCase}
          />
        </div>

        {/* Cost basis, at add time for the same reason as the collection name
            above: the receipt is in hand now. It is also the only figure in
            the app that is a fact rather than an estimate, and nothing else
            can derive it — a hat bought secondhand or on sale has no other
            route to a price except the order-history import, which won't have
            covered it. */}
        <div className="row g-2 mb-3">
          <div className="col-7">
            <label className="form-label" htmlFor="hat-purchase-price">Price paid</label>
            <input
              id="hat-purchase-price"
              type="number"
              inputMode="decimal"
              step="0.01"
              min="0"
              aria-label="Price paid"
              className="form-control"
              placeholder="optional"
              value={values.purchasePrice}
              onChange={e => onChange('purchasePrice', e.target.value)}
            />
          </div>
          <div className="col-5">
            <label className="form-label" htmlFor="hat-purchased-at">Bought on</label>
            <input
              id="hat-purchased-at"
              type="date"
              aria-label="Bought on"
              className="form-control"
              value={values.purchasedAt}
              onChange={e => onChange('purchasedAt', e.target.value)}
            />
          </div>
          <div className="col-12">
            <div className="form-text">
              Drives cost-per-wear and the collection's cost basis. Leave blank
              if you'd rather import it from your order history in Settings.
            </div>
          </div>
        </div>

        <div className="mb-3">
          <label className="form-label">{dateLabel}</label>
          <input
            type="date"
            aria-label={dateLabel}
            className="form-control"
            value={values.dateLastWorn}
            onChange={e => onChange('dateLastWorn', e.target.value)}
          />
        </div>
      </div>
    </div>
  );
}
