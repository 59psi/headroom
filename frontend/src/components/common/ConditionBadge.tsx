import { useHatLabels } from '../../lib/labels';

/**
 * A hat's condition as a badge — the server's label ("New With Tags"), in the
 * DOM as well as on screen.
 *
 * It used to print the raw value with underscores swapped for spaces, "new
 * with tags", and let CSS uppercase it: it LOOKED right, while a screen
 * reader read the lowercase DOM text and a copy-paste gave the stored value.
 * The class still keys on the stored value, which is what the tone is for.
 */
export function ConditionBadge({ condition }: { condition: string }) {
  const labels = useHatLabels();
  return <span className={`badge hr-badge-${condition}`}>{labels.condition(condition)}</span>;
}
