import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getActivityLog } from '../../api/settings';

export function ActivityLogCard() {
  const qc = useQueryClient();
  const activity = useQuery({ queryKey: ['admin', 'activity'], queryFn: () => getActivityLog(50) });

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="d-flex justify-content-between align-items-center mb-2">
          <div className="card-title mb-0">Recent Activity</div>
          <button
            type="button"
            className="btn btn-outline-secondary btn-sm"
            onClick={() => qc.invalidateQueries({ queryKey: ['admin', 'activity'] })}
            disabled={activity.isFetching}
          >{activity.isFetching ? '…' : 'Refresh'}</button>
        </div>
        {(activity.data?.length ?? 0) === 0 ? (
          <p className="text-secondary small mb-0">No activity logged yet.</p>
        ) : (
          <div>
            {activity.data?.slice(0, 25).map(row => (
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
