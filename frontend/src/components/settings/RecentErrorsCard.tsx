import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getRecentErrors, getApiKeyStatus } from '../../api/settings';

export function RecentErrorsCard() {
  const qc = useQueryClient();
  const errors = useQuery({ queryKey: ['admin', 'recent-errors'], queryFn: () => getRecentErrors(20) });
  const apiKey = useQuery({ queryKey: ['settings', 'api-key'], queryFn: getApiKeyStatus });

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="d-flex justify-content-between align-items-center mb-2">
          <div className="card-title mb-0">Recent Analysis Errors</div>
          <button
            type="button"
            className="btn btn-outline-secondary btn-sm"
            onClick={() => qc.invalidateQueries({ queryKey: ['admin', 'recent-errors'] })}
            disabled={errors.isFetching}
          >
            {errors.isFetching ? '…' : 'Refresh'}
          </button>
        </div>
        {errors.data && errors.data.length === 0 ? (
          <p className="text-secondary small mb-0">
            No analysis errors. {apiKey.data?.configured ? '✓' : 'Configure a key to start analyzing.'}
          </p>
        ) : (
          <div>
            {errors.data?.map(err => (
              <Link
                key={err.hat_id}
                to={`/hats/${err.hat_id}`}
                className="hr-color-row text-decoration-none"
                style={{ paddingTop: '0.5rem' }}
              >
                {err.photo_path ? (
                  <img
                    src={`/uploads/${err.photo_path}`}
                    alt=""
                    className="hr-thumb flex-shrink-0"
                    style={{ width: 40, height: 40 }}
                  />
                ) : (
                  <div className="rounded flex-shrink-0" style={{ width: 40, height: 40, background: 'rgba(0,0,0,0.3)' }} />
                )}
                <div className="flex-grow-1" style={{ minWidth: 0 }}>
                  <div className="font-mono small" style={{ color: 'var(--neon-cyan)' }}>
                    {err.display_id || `Hat #${err.hat_id}`}
                  </div>
                  <div className="text-secondary small" style={{
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                  }} title={err.analysis_error || ''}>
                    {err.analysis_error || '(no message)'}
                  </div>
                </div>
                <div className="text-muted small font-mono" style={{ fontSize: '0.7rem' }}>
                  {err.analyzed_at ? new Date(err.analyzed_at).toLocaleString() : ''}
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
