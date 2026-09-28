import { useQuery } from '@tanstack/react-query';
import { getSizes, getStyles } from '../api/hats';

type Option = { value: string | number; label: string };

/**
 * "A-Game" for `a_game`, from the server's option list when it has loaded.
 *
 * The fallback — underscores to spaces — is what every display site did on
 * its own before, which is how the hat page's Specs tile came to read
 * "a game" in lowercase monospace beside a filter chip that, reading the same
 * value through the option list, said "A-Game".
 */
export function optionLabel(opts: ReadonlyArray<Option> | undefined, value: string): string {
  return opts?.find(o => String(o.value) === value)?.label ?? readableValue(value);
}

/**
 * A stored enum value made presentable without the option list: `a_game` →
 * "A Game". For the pages that cannot fetch the list — the guest and shared
 * views have no session, and `/api/meta` sits behind sign-in — and for the
 * moment before it loads everywhere else. Close to the server's label, not
 * identical ("A Game" vs "A-Game"); lowercase "a game" was neither.
 */
export function readableValue(value: string): string {
  return value
    .split('_')
    .filter(Boolean)
    .map(w => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

/**
 * Labels for a hat's enum fields, from the same cached `['meta', …]` queries
 * the filters and the edit form already hold — so on most screens this costs
 * no request at all.
 */
export function useHatLabels() {
  const styles = useQuery({ queryKey: ['meta', 'styles'], queryFn: getStyles });
  const sizes = useQuery({ queryKey: ['meta', 'sizes'], queryFn: getSizes });
  return {
    style: (value: string) => optionLabel(styles.data, value),
    size: (value: string) => optionLabel(sizes.data, value),
  };
}
