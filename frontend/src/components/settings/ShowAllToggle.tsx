import { useState } from 'react';

/**
 * A list that shows its first few until asked for the rest.
 *
 * The backup and restore-point lists both run as long as their retention
 * keeps them — a dozen filenames that differ only in a timestamp is a wall to
 * scroll past on a phone, and the newest few are the ones anybody uses.
 */
export function useShowAll<T>(items: readonly T[], limit: number) {
  const [all, setAll] = useState(false);
  const shown = all ? items : items.slice(0, limit);
  return {
    shown,
    toggle: {
      all,
      total: items.length,
      hidden: items.length - shown.length,
      needed: items.length > limit,
      onToggle: () => setAll(v => !v),
    },
  };
}

export function ShowAllToggle({
  all, total, hidden, needed, onToggle,
}: ReturnType<typeof useShowAll>['toggle']) {
  if (!needed) return null;
  return (
    <button
      type="button"
      className="btn btn-sm btn-outline-secondary hr-upkeep-more"
      aria-expanded={all}
      onClick={onToggle}
    >
      {all ? 'Show fewer' : `Show all ${total} (${hidden} more)`}
    </button>
  );
}
