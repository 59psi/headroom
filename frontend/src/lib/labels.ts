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
  return opts?.find(o => String(o.value) === value)?.label ?? value.replace(/_/g, ' ');
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
