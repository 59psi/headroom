import { Segmented } from '../ui/Segmented';

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

/**
 * The scope as a one-tap strip, shared by Search and the guest page so both
 * ask the question in the same words. The strip itself is `ui/Segmented`,
 * which started life here as `ChoiceGroup` before the other areas' copies of
 * it were folded in.
 */
export function ColorScopePicker({ value, onChange }: {
  value: string;
  onChange: (v: string) => void;
}) {
  return <Segmented label="Color match" options={COLOR_SCOPES} value={value} onChange={onChange} />;
}
