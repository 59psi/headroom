import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { findDuplicates } from '../api/search';
import { ConditionBadge } from '../components/common/ConditionBadge';
import { PageHeader } from '../components/ui/PageHeader';
import { Panel } from '../components/ui/Panel';
import { Skeleton } from '../components/ui/Skeleton';
import { StatusPill } from '../components/ui/StatusPill';
import { tileSrc } from '../lib/photo';
import { hatName, placementLabel } from '../lib/placement';
import { plural } from '../lib/format';
import { qk } from '../lib/queryKeys';
import { LoadError } from '../components/common/LoadError';

/**
 * Hats that look like the same hat entered twice.
 *
 * Reports only — nothing here deletes or merges. Owning the same cap twice,
 * one kept new in the box, is a normal thing, and only the owner knows which
 * case a given pair is. So every row links out to the hat and the decision
 * stays theirs.
 */
export function DuplicatesPage() {
  const dupesQ = useQuery({
    queryKey: qk.duplicates(),
    queryFn: findDuplicates,
  });
  const { data, isLoading, error } = dupesQ;

  const header = (
    <PageHeader
      title="Possible duplicates"
      actions={<Link to="/search" className="btn btn-outline-secondary btn-sm">← Search</Link>}
    />
  );

  if (isLoading) {
    return (
      <>
        {header}
        <div className="card hr-panel">
          <div className="card-body">
            <Skeleton lines={1} />
            <div className="hr-cp-dup-grid mt-3" aria-hidden="true">
              {Array.from({ length: 2 }, (_, i) => (
                <span key={i} className="hr-skeleton hr-cp-skel-square" />
              ))}
            </div>
          </div>
        </div>
      </>
    );
  }

  if (error) {
    return (
      <>
        {header}
        <LoadError what="Couldn’t check for duplicates." queries={[dupesQ]} />
      </>
    );
  }

  const groups = data ?? [];
  const total = groups.reduce((n, g) => n + g.hats.length, 0);

  return (
    <>
      {header}

      {groups.length === 0 ? (
        <div className="hr-cp-empty">
          <div className="hr-cp-empty-icon" aria-hidden="true">✓</div>
          <div className="hr-cp-empty-title">No duplicates found</div>
          <p className="mb-0">
            Every hat with an identified model looks distinct. Hats that
            haven't been analyzed yet aren't compared — there's nothing to
            compare them on.
          </p>
        </div>
      ) : (
        <>
          <p className="hr-cp-lede">
            {plural(total, 'hat')} across {plural(groups.length, 'group')}. Nothing is deleted
            here — open a hat to dispose of it, or leave it if you really do own
            two.
          </p>

          {groups.map(group => (
            <Panel
              key={group.key}
              title={group.label}
              status={
                group.confidence === 'exact' ? (
                  <StatusPill tone="error" title="Every identity field matches">Exact match</StatusPill>
                ) : (
                  <StatusPill
                    tone="warn"
                    title="Same model and size; one of these has no colorway recorded yet"
                  >Likely</StatusPill>
                )
              }
            >
              <div className="hr-cp-dup-grid">
                {group.hats.map(hat => (
                  <Link key={hat.id} to={`/hats/${hat.id}`} className="card hr-hoverable hr-cp-dup-card">
                    <div className="card-body">
                      {hat.photo_path ? (
                        <img
                          src={tileSrc(hat)}
                          alt={hatName(hat)}
                          className="hr-cp-dup-photo"
                        />
                      ) : (
                        <div className="hr-cp-dup-photo hr-cp-dup-nophoto">no photo</div>
                      )}
                      <div className="hr-cp-dup-id">{hatName(hat)}</div>
                      <div className="hr-cp-dup-where">
                        {placementLabel(hat)}
                        {hat.case_display_id && hat.room_name ? ` · ${hat.room_name}` : ''}
                      </div>
                      <div className="mt-1">
                        <ConditionBadge condition={hat.condition} />
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            </Panel>
          ))}
        </>
      )}
    </>
  );
}
