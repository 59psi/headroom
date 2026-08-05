import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getStyles, getSizes, getConditions } from '../../api/hats';
import { listCases } from '../../api/cases';
import { PhotoCapture } from '../photos/PhotoCapture';

/** The fields the Add and Edit hat forms share verbatim. */
export interface HatBasics {
  style: string;
  size: string;
  condition: string;
  /** Case id as a string ('' = unassigned), matching the <select> value. */
  caseId: string;
  /** ISO date or '' */
  dateLastWorn: string;
}

/** Sentinel option value that opens the "create a case" modal instead of selecting one. */
export const NEW_CASE_VALUE = '__new__';

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

  function onCapture(file: File) {
    setPhoto(file);
    setPhotoPreview(URL.createObjectURL(file));
  }

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
          <select className="form-select" value={values.style} onChange={e => onChange('style', e.target.value)}>
            {options.styles.data?.map(s => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </div>

        <div className="mb-3">
          <label className="form-label">Size</label>
          <select className="form-select" value={values.size} onChange={e => onChange('size', e.target.value)}>
            {options.sizes.data?.map(s => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </div>

        <div className="mb-3">
          <label className="form-label">Condition</label>
          <select className="form-select" value={values.condition} onChange={e => onChange('condition', e.target.value)}>
            {options.conditions.data?.map(c => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
        </div>

        <div className="mb-3">
          <label className="form-label">{caseLabel}</label>
          <select className="form-select" value={values.caseId} onChange={e => handleCaseChange(e.target.value)}>
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
            className="form-control"
            value={values.dateLastWorn}
            onChange={e => onChange('dateLastWorn', e.target.value)}
          />
        </div>
      </div>
    </div>
  );
}
