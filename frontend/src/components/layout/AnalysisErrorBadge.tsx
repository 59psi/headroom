import { useQuery } from '@tanstack/react-query';
import { getRecentErrorsCount } from '../../api/settings';
import { plural } from '../../lib/format';
import { qk } from '../../lib/queryKeys';

/**
 * How many hats' ANALYSIS failed — the number both navs pin to the Settings
 * tab. One query, polled once a minute, so the two navs never disagree.
 */
export function useAnalysisErrorCount(): number {
  const errCount = useQuery({
    queryKey: qk.admin.recentErrorsCount(),
    queryFn: getRecentErrorsCount,
    refetchInterval: 60_000,
  });
  return errCount.data?.count ?? 0;
}

export function analysisErrorLabel(count: number): string {
  return `${plural(count, 'hat')} failed analysis`;
}

/**
 * The red count on the Settings tab. Renders nothing at zero.
 *
 * Labeled, because a bare red dot is unreadable to a screen reader and
 * ambiguous to everyone else — it counts hats whose ANALYSIS failed, not
 * errors in general. TopNav and BottomNav each carried their own copy of this
 * markup, and only one of them had the label.
 *
 * Placed entirely by the stylesheet (`.hr-nav-error-badge` in shell.css, per
 * nav). It used to take a `style` prop that no caller passed.
 *
 * The digit caps at "9+": the badge is sized for one character, and past nine
 * the exact number is on the Settings page, one tap away, while the label
 * carries it for a screen reader.
 */
export function AnalysisErrorBadge({ count }: { count: number }) {
  if (count <= 0) return null;
  const label = analysisErrorLabel(count);
  return (
    <span role="status" aria-label={label} title={label} className="hr-nav-error-badge">
      {count > 9 ? '9+' : count}
    </span>
  );
}
