import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorNote } from '../common/ErrorNote';
import { Link } from 'react-router';
import { auditSharedPrices, getUnclaimedFromPurchases } from '../../api/settings';
import { rematchPurchases } from '../../api/purchases';
import { invalidateHatViews, invalidatePurchaseDerived } from '../../lib/invalidate';

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

/** How many hats of a group to name inline. The server sorts colorway-less
 *  hats first, so a truncated sample is the actionable end of the group. */
const SAMPLE_LIMIT = 8;

export function SharedPricesCard() {
  const qc = useQueryClient();
  const audit = useQuery({
    queryKey: ['admin', 'shared-prices'],
    queryFn: auditSharedPrices,
  });
  const { data, isLoading } = audit;

  // Matching runs at the end of an IMPORT and nowhere else, so a better
  // matcher — or a re-analysis that finally gives a hat a model_name — leaves
  // pairs nothing ever looks at again. On the real collection that was 17
  // colorways and 16 prices sitting in already-imported orders while this very
  // card told the owner a colorway was theirs alone to supply.
  const unclaimed = useQuery({
    queryKey: ['admin', 'unclaimed-purchases'],
    queryFn: getUnclaimedFromPurchases,
    // Answering this runs the whole matcher — a full bipartite assignment over
    // every unmatched purchase and every hat — so it is not a free read to
    // repeat on each mount. The backlog only moves when matching runs, and the
    // three places that run it invalidate this key explicitly.
    staleTime: 5 * 60_000,
  });

  const fill = useMutation({
    mutationFn: rematchPurchases,
    onSuccess: () => {
      invalidatePurchaseDerived(qc);
      qc.invalidateQueries({ queryKey: ['admin', 'purchases'] });
      invalidateHatViews(qc);
    },
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

        {/* Outside the groups block on purpose: an unclaimed backlog is worth
            offering whether or not any price is currently shared, and burying
            it inside the "there are groups" branch would hide the offer in the
            one state where acting early prevents the problem. */}
        {(unclaimed.data?.colorways ?? 0) > 0 && (
          <div className="alert alert-info py-2 px-3 mb-3">
            <div className="small mb-2">
              <strong>
                {unclaimed.data!.colorways} colorway
                {unclaimed.data!.colorways === 1 ? '' : 's'} can be filled from
                your own order history
              </strong>{' '}
              — purchases already imported, never matched to a hat.
              {unclaimed.data!.prices > 0 && (
                <> The same run sets {unclaimed.data!.prices} purchase
                  price{unclaimed.data!.prices === 1 ? '' : 's'}.</>
              )}
              {unclaimed.data!.ambiguous > 0 && (
                <> {unclaimed.data!.ambiguous} of them were a tie between
                  equally good candidates — still better than a line median,
                  but worth checking afterwards.</>
              )}
            </div>
            <button
              className="btn btn-sm btn-primary"
              onClick={() => fill.mutate()}
              disabled={fill.isPending}
            >
              {fill.isPending
                ? 'Matching…'
                : `Fill ${unclaimed.data!.colorways} from purchase history`}
            </button>
            <ErrorNote of={fill} what="Matching failed — nothing was changed" />
          </div>
        )}

        <ErrorNote of={[audit, unclaimed]} className="mb-2" />
        {audit.isSuccess && groups.length === 0 && (
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
                      product being named. It cannot be inferred from the photo
                      (measured: 12% precision) — but SOME of them are sitting
                      in the owner's own order history, which is the callout
                      below. This card used to claim the owner was the only
                      possible source, which was false for 17 of 82 hats. */}
                  <div className="hr-metric-label">Missing a colorway</div>
                  <div className="hr-metric-value font-mono">{fixable}</div>
                </div>
              </div>
            </div>

            {fixable > 0 && (
              <p className="text-secondary small mb-3">
                The rest need you: hats with no colorway are listed first and
                link straight to their edit form. Adding a colorway there lets
                that hat be priced against its own product instead of its line.
              </p>
            )}

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
                    {/* Each hat carries its own label, so nothing is indexed
                        against a second array that can fall out of step. A hat
                        with no case has no display_id — normal for a
                        room-stored one — and shows its id instead. */}
                    {g.hats.slice(0, SAMPLE_LIMIT).map((h, i) => (
                      <span key={h.hat_id}>
                        {i > 0 && ' · '}
                        <Link
                          to={h.has_colorway
                            ? `/hats/${h.hat_id}`
                            : `/hats/${h.hat_id}/edit`}
                          title={h.has_colorway
                            ? undefined
                            : 'No colorway recorded — add one to price this hat on its own product'}
                        >
                          {h.display_id ?? `#${h.hat_id}`}
                          {!h.has_colorway && ' *'}
                        </Link>
                      </span>
                    ))}
                    {/* Stated, never silent — a truncated list must not read
                        as the whole group. */}
                    {g.hat_count > SAMPLE_LIMIT && (
                      <span className="text-muted">
                        {' '}and {g.hat_count - SAMPLE_LIMIT} more
                      </span>
                    )}
                  </div>
                </li>
              ))}
            </ul>

            {fixable > 0 && (
              <div className="text-muted" style={{ fontSize: '0.72rem' }}>
                * no colorway recorded
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
