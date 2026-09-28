import { useMemo } from 'react';
import { Link } from 'react-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorNote } from '../common/ErrorNote';
import { getActivityLog, getRetentionStatus } from '../../api/settings';
import type { ActivityRow, RetentionStatus } from '../../types';
import { timeAgo } from '../../lib/format';
import { Panel } from '../ui/Panel';
import { StatusPill } from '../ui/StatusPill';
import { Skeleton } from '../ui/Skeleton';

const ROWS_SHOWN = 25;

/**
 * The dot on the timeline, by what kind of thing happened.
 *
 * Decoration on top of the kind, which is printed beside it — never the only
 * carrier. Suffix-matched against the server's `noun.verb` kinds, so a kind
 * added later falls through to the neutral dot rather than to a wrong color.
 */
function kindTone(kind: string): 'bad' | 'gone' | 'new' | 'neutral' {
  if (/^error\.|_failed$|_blocked$/.test(kind)) return 'bad';
  if (/\.(deleted|cleared|revoked|disposed|canceled|removed)$|_cleared$|_removed$|unmatched/.test(kind)) return 'gone';
  if (/\.(created|setup)$|_added$|_configured$/.test(kind)) return 'new';
  return 'neutral';
}

/**
 * Where a row's subject lives, when it still does. Hats and rooms route by
 * the numeric id the log records; cases route by display id, which the log
 * does not carry, so they stay plain text rather than link to a guess. A
 * deleted subject has no page to open.
 */
function subjectHref(row: ActivityRow): string | null {
  if (row.entity_id == null || row.kind.endsWith('.deleted')) return null;
  if (row.entity_type === 'hat') return `/hats/${row.entity_id}`;
  if (row.entity_type === 'room') return `/rooms/${row.entity_id}`;
  return null;
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** "Today", "Yesterday", else a short date (with the year once it differs). */
function dayLabel(d: Date, now: Date): string {
  const days = Math.round((startOfDay(now) - startOfDay(d)) / 86_400_000);
  if (days === 0) return 'Today';
  if (days === 1) return 'Yesterday';
  return d.toLocaleDateString(undefined, {
    weekday: 'short', month: 'short', day: 'numeric',
    ...(d.getFullYear() !== now.getFullYear() ? { year: 'numeric' } : {}),
  });
}

/**
 * Rows grouped under a heading per day. Twenty-five full timestamps in a
 * column repeat the same date twenty-five times; under a day heading each row
 * only needs its time, and "what happened this morning" reads at a glance.
 * The rows arrive newest-first, so consecutive grouping keeps that order.
 */
function groupByDay(rows: ActivityRow[]) {
  const now = new Date();
  const groups: { key: number; label: string; rows: ActivityRow[] }[] = [];
  for (const row of rows) {
    const d = new Date(row.occurred_at);
    const key = startOfDay(d);
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.rows.push(row);
    else groups.push({ key, label: dayLabel(d, now), rows: [row] });
  }
  return groups;
}

/**
 * The retention prune's state, for the card header. The daily prune is the
 * only thing bounding this table and `auth_sessions`, so its health IS this
 * card's state — the rows themselves are fine either way.
 */
function RetentionPill({ r }: { r: RetentionStatus }) {
  const h = r.health;
  if (h.consecutive_failures > 0) return <StatusPill tone="error">Prune failing</StatusPill>;
  if (h.last_success_at) {
    return (
      <StatusPill tone="ok" title={`Entries older than ${r.retention_days} days are pruned daily.`}>
        Keeps {r.retention_days} days
      </StatusPill>
    );
  }
  return <StatusPill tone="off">Prune pending</StatusPill>;
}

function RetentionNote({ r }: { r: RetentionStatus }) {
  const h = r.health;
  if (h.consecutive_failures > 0) {
    return (
      <p className="hr-upkeep-alert">
        Retention prune failing ({h.consecutive_failures} in a row)
        {h.last_error ? `: ${h.last_error}` : ''}. Both this log and expired
        sessions are growing unbounded.
      </p>
    );
  }
  if (h.last_success_at) {
    return (
      <p className="hr-upkeep-note">
        Pruned {h.last_result} row{h.last_result === 1 ? '' : 's'} older than{' '}
        {r.retention_days} days,{' '}
        <time dateTime={h.last_success_at} title={new Date(h.last_success_at).toLocaleString()}>
          {timeAgo(h.last_success_at)}
        </time>.
      </p>
    );
  }
  // Process-local, so this is the honest reading after a restart: the loop
  // prunes first and sleeps after, but until it has, the record has nothing
  // to report and must not imply it does.
  return <p className="hr-upkeep-note">Retention has not run yet since the last restart.</p>;
}

export function ActivityLogCard() {
  const qc = useQueryClient();
  // Fetches exactly what it shows — it asked for 50 and sliced to 25.
  const activity = useQuery({ queryKey: ['admin', 'activity'], queryFn: () => getActivityLog(ROWS_SHOWN) });
  // The daily prune is the only thing bounding this table and `auth_sessions`,
  // and it had no health record of any kind — a persistent failure was one
  // WARNING per day into a container log while an SD card filled. The row
  // count below cannot stand in for it: a table nobody is writing to and a
  // prune that died three weeks ago look identical from a count.
  const retention = useQuery({
    queryKey: ['admin', 'retention'], queryFn: getRetentionStatus,
  });
  // Above any early exit (there is none today — keep it that way): a hook
  // after a conditional return is the Rules-of-Hooks bug CLAUDE.md warns of.
  const groups = useMemo(() => groupByDay(activity.data ?? []), [activity.data]);
  const refreshing = activity.isFetching || retention.isFetching;

  return (
    <Panel
      title="Recent activity"
      className="hr-upkeep-card"
      status={retention.data && <RetentionPill r={retention.data} />}
      actions={
        <button
          type="button"
          className="btn btn-outline-secondary btn-sm"
          onClick={() => {
            qc.invalidateQueries({ queryKey: ['admin', 'activity'] });
            // A SIBLING key: the retention sentence rendered below reads it,
            // and "activity" is not a prefix of "retention" (CLAUDE.md).
            qc.invalidateQueries({ queryKey: ['admin', 'retention'] });
          }}
          disabled={refreshing}
          aria-busy={refreshing || undefined}
        >
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </button>
      }
      description={`Sign-ins, settings changes and edits — the newest ${ROWS_SHOWN}.`}
      help={
        <p>
          Headroom records changes as they happen — hats added, edited,
          disposed or deleted; cases and rooms created or removed; keys,
          settings and share links changed; imports, exports and backup
          downloads; unexpected server errors — and every sign-in, including
          failed and blocked attempts. Linked entries open the hat or room they
          are about. A daily prune removes entries older than{' '}
          {retention.data ? `${retention.data.retention_days} days` : 'the retention window'}{' '}
          together with expired sign-in sessions; it is the only thing that
          keeps either from growing without bound.
        </p>
      }
    >
      {retention.data && <RetentionNote r={retention.data} />}
      <ErrorNote of={[activity, retention]} className="mb-3" />
      {activity.isPending ? (
        <Skeleton lines={4} />
      ) : activity.isSuccess && activity.data.length === 0 ? (
        <p className="hr-upkeep-note mb-0">No activity logged yet.</p>
      ) : (
        <div className="hr-upkeep-timeline">
          {groups.map(g => (
            // A heading per day (under the card's h2), not a labeled
            // <section>: a named section is a landmark, and one per day would
            // bury the page's real landmarks under a list of dates.
            <div key={g.key} className="hr-upkeep-day">
              <h3 className="hr-upkeep-day-label">{g.label}</h3>
              <ol className="hr-upkeep-events">
                {g.rows.map(row => {
                  const href = subjectHref(row);
                  const at = new Date(row.occurred_at);
                  return (
                    <li key={row.id} className={`hr-upkeep-event is-${kindTone(row.kind)}`}>
                      <span className="hr-upkeep-event-dot" aria-hidden="true" />
                      <div className="hr-upkeep-event-body">
                        <div className="hr-upkeep-event-summary">
                          {href ? <Link to={href}>{row.summary}</Link> : row.summary}
                        </div>
                        <div className="hr-upkeep-event-meta">
                          <time dateTime={row.occurred_at} title={at.toLocaleString()}>
                            {at.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}
                          </time>
                          <span className="hr-upkeep-event-kind">{row.kind}</span>
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
