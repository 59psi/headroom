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
  return (
    <div className="btn-group" role="group" aria-label="Color match">
      {COLOR_SCOPES.map(s => (
        <button
          key={s.value}
          type="button"
          aria-pressed={value === s.value}
          className={`btn btn-sm ${value === s.value ? 'btn-primary' : 'btn-outline-primary'}`}
          onClick={() => onChange(s.value)}
        >{s.label}</button>
      ))}
    </div>
  );
}
