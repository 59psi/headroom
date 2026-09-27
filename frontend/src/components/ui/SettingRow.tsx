import type { ReactNode } from 'react';

/**
 * Label and explanation on the left, the control on the right; stacked on a
 * phone. The layout every mature settings screen converges on, because the
 * eye can run down the left edge to find a setting and down the right edge to
 * read the values.
 */
export function SettingRow({
  label,
  hint,
  htmlFor,
  children,
  trailing,
}: {
  label: ReactNode;
  hint?: ReactNode;
  /** `id` of the control, so the label is its accessible name. */
  htmlFor?: string;
  children: ReactNode;
  /** Small note under the control: a `SaveState`, a unit. */
  trailing?: ReactNode;
}) {
  return (
    <div className="hr-setting-row">
      <div className="hr-setting-text">
        {htmlFor
          ? <label className="hr-setting-label" htmlFor={htmlFor}>{label}</label>
          : <span className="hr-setting-label">{label}</span>}
        {hint && <span className="hr-setting-hint">{hint}</span>}
      </div>
      <div className="hr-setting-control">
        {children}
        {trailing && <div className="hr-setting-trailing">{trailing}</div>}
      </div>
    </div>
  );
}
