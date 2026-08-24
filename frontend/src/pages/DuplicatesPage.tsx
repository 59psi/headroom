import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { findDuplicates } from '../api/search';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ConditionBadge } from '../components/common/ConditionBadge';
import { tileSrc } from '../lib/photo';

/**
 * Hats that look like the same hat entered twice.
 *
 * Reports only — nothing here deletes or merges. Owning the same cap twice,
 * one kept new in the box, is a normal thing, and only the owner knows which
 * case a given pair is. So every row links out to the hat and the decision
 * stays theirs.
 */
export function DuplicatesPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['duplicates'],
    queryFn: findDuplicates,
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <div className="alert alert-danger">Couldn't check for duplicates.</div>;

  const groups = data ?? [];
  const total = groups.reduce((n, g) => n + g.hats.length, 0);

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3 gap-2 flex-wrap">
        <h1>Possible Duplicates</h1>
        <Link to="/search" className="btn btn-outline-secondary btn-sm">← Search</Link>
      </div>

      {groups.length === 0 ? (
        <div className="card">
          <div className="card-body text-center py-5">
            <div className="fs-4 mb-2">✓</div>
            <div className="fw-semibold mb-1">No duplicates found</div>
            <p className="text-secondary small mb-0">
              Every hat with an identified model looks distinct. Hats that
              haven't been analyzed yet aren't compared — there's nothing to
              compare them on.
            </p>
          </div>
        </div>
      ) : (
        <>
          <p className="text-secondary small mb-3">
            {total} hats across {groups.length}{' '}
            {groups.length === 1 ? 'group' : 'groups'}. Nothing is deleted
            here — open a hat to dispose of it, or leave it if you really do own
            two.
          </p>

          {groups.map(group => (
            <div className="card mb-3" key={group.key}>
              <div className="card-body">
                <div className="d-flex justify-content-between align-items-center gap-2 flex-wrap mb-3">
                  <div className="card-title mb-0">{group.label}</div>
                  <span
                    className={`badge ${group.confidence === 'exact' ? 'bg-danger' : 'bg-warning'}`}
                    title={
                      group.confidence === 'exact'
                        ? 'Every identity field matches'
                        : 'Same model and size; one of these has no colorway recorded yet'
                    }
                  >
                    {group.confidence === 'exact' ? 'exact match' : 'likely'}
                  </span>
                </div>

                <div className="row g-2">
                  {group.hats.map(hat => (
                    <div className="col-6 col-lg-3" key={hat.id}>
                      <Link to={`/hats/${hat.id}`} className="card hr-hoverable h-100">
                        <div className="card-body p-2">
                          {hat.photo_path ? (
                            <img
                              src={tileSrc(hat)}
                              alt={hat.display_id || `Hat ${hat.id}`}
                              className="w-100 mb-2"
                              style={{ aspectRatio: '1', objectFit: 'contain' }}
                            />
                          ) : (
                            <div
                              className="w-100 mb-2 d-flex align-items-center justify-content-center text-muted"
                              style={{ aspectRatio: '1' }}
                            >
                              no photo
                            </div>
                          )}
                          <div className="font-mono small">
                            {hat.display_id || `#${hat.id}`}
                          </div>
                          <div className="text-secondary" style={{ fontSize: '0.7rem' }}>
                            {hat.case_display_id || 'Unassigned'}
                            {hat.room_name ? ` · ${hat.room_name}` : ''}
                          </div>
                          <div className="mt-1">
                            <ConditionBadge condition={hat.condition} />
                          </div>
                        </div>
                      </Link>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </>
      )}
    </>
  );
}
