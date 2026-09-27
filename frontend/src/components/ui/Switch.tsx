import { useId, type ReactNode } from 'react';

/**
 * An on/off setting that applies the moment it is flipped.
 *
 * A checkbox followed by a Save button asks for two taps and leaves the page
 * in a half-state in between (the box says on, the server says off). A switch
 * means "this is live": the caller saves in `onChange`, optimistically, and
 * the switch shows the new position immediately.
 *
 * `role="switch"` on a real <button>, so Space and Enter both toggle and the
 * state is announced as "on"/"off" rather than "checked".
 */
export function Switch({
  checked,
  onChange,
  label,
  hint,
  disabled = false,
  busy = false,
  id,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: ReactNode;
  hint?: ReactNode;
  disabled?: boolean;
  /** A save is in flight: the knob pulses, input stays enabled. */
  busy?: boolean;
  id?: string;
}) {
  const auto = useId();
  const labelId = `${id ?? auto}-label`;
  const hintId = `${id ?? auto}-hint`;
  return (
    <div className={`hr-switch-row${disabled ? ' is-disabled' : ''}`}>
      <div className="hr-switch-text">
        <span className="hr-switch-label" id={labelId}>{label}</span>
        {hint && <span className="hr-switch-hint" id={hintId}>{hint}</span>}
      </div>
      <button
        type="button"
        role="switch"
        id={id}
        aria-checked={checked}
        aria-labelledby={labelId}
        aria-describedby={hint ? hintId : undefined}
        aria-busy={busy || undefined}
        disabled={disabled}
        className={`hr-switch${checked ? ' is-on' : ''}${busy ? ' is-busy' : ''}`}
        onClick={() => onChange(!checked)}
      >
        <span className="hr-switch-knob" aria-hidden="true" />
      </button>
    </div>
  );
}
