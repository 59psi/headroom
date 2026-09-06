import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorNote } from '../common/ErrorNote';
import { getActivityLog, getRetentionStatus } from '../../api/settings';

const ROWS_SHOWN = 25;

export function ActivityLogCard() {
  const qc = useQueryClient();
  // Fetches exactly what it shows — it asked for 50 and sliced to 25.
  const activity = useQuery({ queryKey: ['admin', 'activity'], queryFn: () => getActivityLog(ROWS_SHOWN) });
  // The daily prune is the only thing bounding this table and `auth_sessions`,
  // and it had no health record of any kind — a persistent failure was one
  // WARNING per day into a container log while an SD card filled. The row
  // count above cannot stand in for it: a table nobody is writing to and a
  // prune that died three weeks ago look identical from a count.
  const retention = useQuery({
    queryKey: ['admin', 'retention'], queryFn: getRetentionStatus,
  });
  const health = retention.data?.health;

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="d-flex justify-content-between align-items-center mb-2">
          <div className="card-title mb-0">Recent Activity</div>
          <button
            type="button"
            className="btn btn-outline-secondary btn-sm"
            onClick={() => {
              qc.invalidateQueries({ queryKey: ['admin', 'activity'] });
              // A SIBLING key: the retention sentence rendered below reads it,
              // and "activity" is not a prefix of "retention" (CLAUDE.md).
              qc.invalidateQueries({ queryKey: ['admin', 'retention'] });
            }}
            disabled={activity.isFetching}
          >{activity.isFetching ? '…' : 'Refresh'}</button>
        </div>
        {health && (
          <p className="text-secondary small mb-2">
            {health.consecutive_failures > 0 ? (
              <span style={{ color: 'var(--neon-red)' }}>
                Retention prune failing ({health.consecutive_failures} in a row)
                {health.last_error ? `: ${health.last_error}` : ''}. Both this log
                and expired sessions are growing unbounded.
              </span>
            ) : health.last_success_at ? (
              <>
                Pruned {health.last_result} row{health.last_result === 1 ? '' : 's'}
                {' '}older than {retention.data?.retention_days} days,{' '}
                {new Date(health.last_success_at).toLocaleString()}.
              </>
            ) : (
              // Process-local, so this is the honest reading after a restart:
              // the loop prunes first and sleeps after, but until it has, the
              // record has nothing to report and must not imply it does.
              <>Retention has not run yet since the last restart.</>
            )}
          </p>
        )}
        <ErrorNote of={[activity, retention]} className="mb-2" />
        {activity.isSuccess && activity.data.length === 0 ? (
          <p className="text-secondary small mb-0">No activity logged yet.</p>
        ) : (
          <div>
            {activity.data?.map(row => (
              <div key={row.id} className="hr-color-row" style={{ paddingTop: '0.5rem' }}>
                <div className="flex-grow-1" style={{ minWidth: 0 }}>
                  <div className="small" style={{
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                  }}>{row.summary}</div>
                  <div className="text-muted small font-mono" style={{ fontSize: '0.7rem' }}>
                    {row.kind}
                  </div>
                </div>
                <div className="text-muted small font-mono" style={{ fontSize: '0.7rem' }}>
                  {new Date(row.occurred_at).toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
