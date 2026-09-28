import type { MetaOption } from '../../types';

/**
 * A labeled select over one of the `/api/meta` option lists — style, size,
 * condition — the control every hat form offers for them.
 *
 * Bulk import hand-wrote four of these (label, id, `options.map`) beside the
 * Add/Edit forms' own three; one definition, so a change to how an enum is
 * picked (its label, its id, a placeholder) is one edit rather than a hunt.
 */
export function OptionSelect({
  id,
  label,
  value,
  onChange,
  options,
  className,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (next: string) => void;
  options: readonly MetaOption[] | undefined;
  /** On the wrapper — a grid placement such as `hr-form-grid-wide`. */
  className?: string;
}) {
  return (
    <div className={className}>
      <label className="form-label" htmlFor={id}>{label}</label>
      <select id={id} className="form-select" value={value} onChange={e => onChange(e.target.value)}>
        {options?.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}
