import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { auditSharedPrices } from '../../api/settings';

/**
 * Which resale prices describe a LINE rather than the hat beside them.
 *
 * The reported complaint was that values "are all very wrong". They were not
 * individually implausible — they were *identical*: 168 of 235 hats carried one
 * of five numbers, 54 of them at exactly $85.00. Nothing in the app said so.
 * Each hat's page showed its own figure with its own source sentence, and only
 * a query across the whole collection revealed the overlap.
 *
 * Pricing prefers melin's own product now, which splits a line into real goods
 * — but only for a hat whose product can be identified. For many it cannot, and
 * guessing was measured at 12% precision, so the honest move is to say which
 * numbers are line-level rather than invent precision they do not have.
 */
export function SharedPricesCard() {
  const { data, isLoading } = useQuery({
    queryKey: ['admin', 'shared-prices'],
    queryFn: auditSharedPrices,
  });

  const groups = data ?? [];
  const hats = groups.reduce((n, g) => n + g.hat_count, 0);
  const fixable = groups.reduce((n, g) => n + g.missing_colorway, 0);

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Prices shared by many hats</div>
        <p className="text-secondary small mb-3">
          A resale figure carried by dozens of hats at once is the going rate for
          a <em>line</em>, not an appraisal of any one of them. Melin Recap only
          lists a handful of any given model, so where a hat&rsquo;s exact
          product can&rsquo;t be identified this is the best available signal —
          worth knowing, rather than reading as a per-hat valuation.
        </p>

        {isLoading && <div className="text-secondary small">Loading…</div>}

        {!isLoading && groups.length === 0 && (
          <div className="text-secondary small">
            Nothing shared by more than a few hats — every price is describing
            its own hat.
          </div>
        )}

        {groups.length > 0 && (
          <>
            <div className="row g-2 mb-3">
              <div className="col-6">
                <div className="hr-metric">
                  <div className="hr-metric-label">Hats affected</div>
                  <div className="hr-metric-value font-mono">{hats}</div>
                </div>
              </div>
              <div className="col-6">
                <div className="hr-metric">
                  {/* The actionable half. A missing colorway is what stops a
                      product being named, and it is the one thing only the
                      owner can supply — it cannot be inferred from the photo
                      (measured: 12% precision) or from an unmatched receipt. */}
                  <div className="hr-metric-label">Missing a colorway</div>
                  <div className="hr-metric-value font-mono">{fixable}</div>
                </div>
              </div>
            </div>

            <ul className="hr-plain-list">
              {groups.map(g => (
                <li key={`${g.resale_price}-${g.source ?? ''}`} className="mb-3">
                  <div className="d-flex justify-content-between align-items-baseline">
                    <span className="fw-semibold font-mono">
                      ${g.resale_price.toFixed(2)}
                    </span>
                    <span className="text-secondary small">
                      {g.hat_count} hat{g.hat_count === 1 ? '' : 's'}
                    </span>
                  </div>
                  {g.source && (
                    <div className="text-muted" style={{ fontSize: '0.72rem' }}>
                      {g.source}
                    </div>
                  )}
                  {g.missing_colorway > 0 && (
                    <div className="text-secondary small">
                      {g.missing_colorway} of these have no colorway recorded —
                      adding one lets that hat be priced against its own product.
                    </div>
                  )}
                  <div className="small">
                    {g.hat_ids.slice(0, 8).map((id, i) => (
                      <span key={id}>
                        {i > 0 && ' · '}
                        <Link to={`/hats/${id}`}>
                          {g.display_ids[i] ?? `#${id}`}
                        </Link>
                      </span>
                    ))}
                    {/* Stated, never silent — a truncated list must not read
                        as the whole group. */}
                    {g.hat_ids.length > 8 && (
                      <span className="text-muted">
                        {' '}and {g.hat_ids.length - 8} more
                      </span>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
