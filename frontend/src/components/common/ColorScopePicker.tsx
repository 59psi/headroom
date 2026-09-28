/**
 * A row of mutually exclusive choices, one tap each.
 *
 * Short fixed lists (a color scope, how a hat left the collection, a swatch's
 * tier) used to be either a `<select>` — two taps and, on iOS, a picker wheel
 * for four words that fit on screen at once — or a `btn-group` whose selected
 * button was a solid gradient `btn-primary`, the loudest thing on the page
 * for what is only a filter. Here the choice is visible, one tap changes it,
 * and the selected option is marked by a quiet lit surface instead.
 *
 * Toggle buttons (`aria-pressed`) in a labeled group rather than radios, so
 * each option stays a plain `button` by name — the Search and Guest pages'
 * tests and assistive tech both find "Accents only" as a button.
 *
 * `segmented` is one joined strip (filters); `chips` are separate pills that
 * wrap (form choices in a modal, where five options need two lines on a
 * phone). Lives here, beside its first user, until it is promoted to
 * `components/ui`.
 */
export function ChoiceGroup({
  options,
  value,
  onChange,
  label,
  labelledBy,
  variant = 'segmented',
}: {
  options: ReadonlyArray<{ value: string; label: string }>;
  value: string;
  onChange: (v: string) => void;
  /** Accessible name when there is no visible label to point at. */
  label?: string;
  /** `id` of a visible label, preferred over `label`. */
  labelledBy?: string;
  variant?: 'segmented' | 'chips';
}) {
  return (
    <div
      className={`hr-choice is-${variant}`}
      role="group"
      aria-label={labelledBy ? undefined : label}
      aria-labelledby={labelledBy}
    >
      {options.map(o => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          className={`hr-choice-btn${value === o.value ? ' is-active' : ''}`}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/**
 * Which swatches a color term is allowed to match.
 *
 * The default is the hat's own colors. Every melin hat is a dark crown with a
 * bright mark on it, so matching every swatch made color terms nearly
 * useless — searching "pink" returned every black cap with a pink logo, and
 * the accent colors are precisely the ones that vary.
 *
 * "Accent" is its own question rather than the leftovers: *which of my hats
 * has pink on it somewhere* is how you look for a collab mark or a contrast
 * underbrim.
 */
export const COLOR_SCOPES = [
  { value: 'major', label: 'Main colors' },
  { value: 'accent', label: 'Accents only' },
  { value: 'all', label: 'Any' },
] as const;

export function ColorScopePicker({ value, onChange }: {
  value: string;
  onChange: (v: string) => void;
}) {
  return <ChoiceGroup label="Color match" options={COLOR_SCOPES} value={value} onChange={onChange} />;
}
