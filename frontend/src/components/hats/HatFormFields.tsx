import { useState, useRef, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getStyles, getSizes, getConditions } from '../../api/hats';
import { listCases } from '../../api/cases';
import { PhotoCapture } from '../photos/PhotoCapture';

/** The fields the Add and Edit hat forms share verbatim. */
export interface HatBasics {
  style: string;
  size: string;
  condition: string;
  /** melin HYDROLite construction — orthogonal to style, so any model can be one. */
  hydrolite: boolean;
  /** melin HYDRO construction — the sibling technology, likewise any model. */
  hydro: boolean;
  /** Case id as a string ('' = unassigned), matching the <select> value. */
  caseId: string;
  /** ISO date or '' */
  dateLastWorn: string;
}

/** Sentinel option value that opens the "create a case" modal instead of selecting one. */
export const NEW_CASE_VALUE = '__new__';

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
  style: string; size: string; condition: string; hydrolite: boolean; hydro: boolean;
} = {
  style: 'a_game',
  size: 'classic',
  condition: 'new',
  hydrolite: false,
  hydro: false,
};

/** The four dropdown sources both hat forms need, plus a single loading flag. */
export function useHatFormOptions() {
  const styles = useQuery({ queryKey: ['meta', 'styles'], queryFn: getStyles });
  const sizes = useQuery({ queryKey: ['meta', 'sizes'], queryFn: getSizes });
  const conditions = useQuery({ queryKey: ['meta', 'conditions'], queryFn: getConditions });
  const cases = useQuery({ queryKey: ['cases'], queryFn: listCases });

  return {
    styles, sizes, conditions, cases,
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
  function handleCaseChange(value: string) {
    if (value === NEW_CASE_VALUE) onCreateCase();
    else onChange('caseId', value);
  }

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
            "a HYDROLite instead of a Coronado". Two independent checkboxes and
            not a 3-way radio — realistically a hat is one or the other, but the
            schema doesn't enforce that, so the form shouldn't either. Claude
            picks at most one; a person can record whatever the hat says. */}
        <div className="mb-3">
          <label className="form-label">Construction</label>
          <label className="d-flex align-items-center gap-2 mb-2" style={{ cursor: 'pointer' }}>
            <input
              type="checkbox"
              aria-label="HYDROLite construction"
              checked={values.hydrolite}
              onChange={e => onChange('hydrolite', e.target.checked)}
              style={{ width: 20, height: 20, flexShrink: 0 }}
            />
            <span>
              HYDROLite
              <span className="text-secondary small d-block">
                Featherweight, bonded seams, gel-welded logo, antimicrobial sweatband
              </span>
            </span>
          </label>
          <label className="d-flex align-items-center gap-2" style={{ cursor: 'pointer' }}>
            <input
              type="checkbox"
              aria-label="HYDRO construction"
              checked={values.hydro}
              onChange={e => onChange('hydro', e.target.checked)}
              style={{ width: 20, height: 20, flexShrink: 0 }}
            />
            <span>
              HYDRO
              <span className="text-secondary small d-block">
                Water-resistant build — usually named in the model ("A-Game Hydro")
              </span>
            </span>
          </label>
        </div>

        <div className="mb-3">
          <label className="form-label">{caseLabel}</label>
          <select aria-label={caseLabel} className="form-select" value={values.caseId} onChange={e => handleCaseChange(e.target.value)}>
            <option value="">Unassigned</option>
            <option value={NEW_CASE_VALUE}>+ Create New Case…</option>
            {options.cases.data?.map(c => (
              <option key={c.id} value={c.id}>
                {c.display_id} ({c.case_type === 'archive' ? 'Archive' : 'Daily'} · {c.hat_count} hats · {c.room_name})
              </option>
            ))}
          </select>
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
