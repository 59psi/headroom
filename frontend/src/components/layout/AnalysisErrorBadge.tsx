import type { CSSProperties } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getRecentErrorsCount } from '../../api/settings';

/**
 * How many hats' ANALYSIS failed — the number both navs pin to the Settings
 * tab. One query, polled once a minute, so the two navs never disagree.
 */
export function useAnalysisErrorCount(): number {
  const errCount = useQuery({
    queryKey: ['admin', 'recent-errors-count'],
    queryFn: getRecentErrorsCount,
    refetchInterval: 60_000,
  });
  return errCount.data?.count ?? 0;
}

export function analysisErrorLabel(count: number): string {
  return `${count} hat${count === 1 ? '' : 's'} failed analysis`;
}

/**
 * The red count on the Settings tab. Renders nothing at zero.
 *
 * Labeled, because a bare red dot is unreadable to a screen reader and
 * ambiguous to everyone else — it counts hats whose ANALYSIS failed, not
 * errors in general. TopNav and BottomNav each carried their own copy of this
 * markup, and only one of them had the label.
 */
export function AnalysisErrorBadge({ count, style }: { count: number; style?: CSSProperties }) {
  if (count <= 0) return null;
  const label = analysisErrorLabel(count);
  return (
    <span role="status" aria-label={label} title={label} className="hr-nav-error-badge" style={style}>
      {count > 9 ? '9+' : count}
    </span>
  );
}
