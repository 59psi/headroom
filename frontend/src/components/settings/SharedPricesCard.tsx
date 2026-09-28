import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorNote } from '../common/ErrorNote';
import { Link } from 'react-router';
import { auditSharedPrices, getUnclaimedFromPurchases } from '../../api/settings';
import { rematchPurchases } from '../../api/purchases';
import { plural } from '../../lib/format';
import { invalidateHatViews, invalidatePurchaseDerived } from '../../lib/invalidate';
import { hatName } from '../../lib/placement';
import { qk } from '../../lib/queryKeys';
import { Panel } from '../ui/Panel';
import { StatusPill } from '../ui/StatusPill';
import { Skeleton } from '../ui/Skeleton';
import { useToast } from '../ui/Toast';

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
  const toast = useToast();
  const audit = useQuery({
    queryKey: qk.admin.sharedPrices(),
    queryFn: auditSharedPrices,
  });
  const { data, isLoading } = audit;

  // Matching runs at the end of an IMPORT and nowhere else, so a better
  // matcher — or a re-analysis that finally gives a hat a model_name — leaves
  // pairs nothing ever looks at again. On the real collection that was 17
  // colorways and 16 prices sitting in already-imported orders while this very
  // card told the owner a colorway was theirs alone to supply.
  const unclaimed = useQuery({
    queryKey: qk.admin.unclaimedPurchases(),
    queryFn: getUnclaimedFromPurchases,
    // Answering this runs the whole matcher — a full bipartite assignment over
    // every unmatched purchase and every hat — so it is not a free read to
    // repeat on each mount. The backlog only moves when matching runs, and the
    // three places that run it invalidate this key explicitly.
    staleTime: 5 * 60_000,
  });

  const fill = useMutation({
    mutationFn: rematchPurchases,
    onSuccess: result => {
      toast.success(`Matched ${plural(result.matched, 'purchase')} from your order history`);
      // The purchase list, the unclaimed offer this button sits in, and this
      // report — all derived from matching — then every hat it wrote onto.
      invalidatePurchaseDerived(qc);
      void invalidateHatViews(qc);
    },
  });

  const groups = data ?? [];
  const hats = groups.reduce((n, g) => n + g.hat_count, 0);
  const fixable = groups.reduce((n, g) => n + g.missing_colorway, 0);

  return (
    <Panel
      title="Prices shared by many hats"
      status={audit.isSuccess && (groups.length
        ? <StatusPill tone="info">{plural(hats, 'hat')}</StatusPill>
        : <StatusPill tone="ok">Nothing shared</StatusPill>)}
      description="A resale figure many hats share is a line's going rate, not an appraisal of any one hat."
      help={
        <p>
          A resale figure carried by dozens of hats at once is the going rate for
          a <em>line</em>, not an appraisal of any one of them. Melin Recap only
          lists a handful of any given model, so where a hat&rsquo;s exact
          product can&rsquo;t be identified this is the best available signal —
          worth knowing, rather than reading as a per-hat valuation. A colorway
          is what lets a hat be priced against its own product instead.
        </p>
      }
    >
      {isLoading && <Skeleton lines={3} />}

      {/* Outside the groups block on purpose: an unclaimed backlog is worth
          offering whether or not any price is currently shared, and burying
          it inside the "there are groups" branch would hide the offer in the
          one state where acting early prevents the problem. */}
      {(unclaimed.data?.colorways ?? 0) > 0 && (
        <div className="hr-sd-callout mb-3">
          <p className="small mb-2">
            <strong>
              {plural(unclaimed.data!.colorways, 'colorway')} can be filled from
              your own order history
            </strong>{' '}
            — purchases already imported, never matched to a hat.
            {unclaimed.data!.prices > 0 && (
              <> The same run sets {plural(unclaimed.data!.prices, 'purchase price')}.</>
            )}
            {unclaimed.data!.ambiguous > 0 && (
              <> {unclaimed.data!.ambiguous} of them were a tie between
                equally good candidates — still better than a line median,
                but worth checking afterwards.</>
            )}
          </p>
          <button
            type="button"
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
        <p className="text-secondary small mb-0">
          Nothing shared by more than a few hats — every price is describing
          its own hat.
        </p>
      )}

      {groups.length > 0 && (
        <>
          <dl className="hr-metric-grid hr-sd-metrics mb-3">
            <div className="hr-metric">
              <dt className="hr-metric-label">Hats affected</dt>
              <dd className="hr-metric-value">{hats}</dd>
            </div>
            <div className="hr-metric">
              {/* The actionable half. A missing colorway is what stops a
                  product being named. It cannot be inferred from the photo
                  (measured: 12% precision) — but SOME of them are sitting
                  in the owner's own order history, which is the callout
                  above. This card used to claim the owner was the only
                  possible source, which was false for 17 of 82 hats. */}
              <dt className="hr-metric-label">Missing a colorway</dt>
              <dd className="hr-metric-value">{fixable}</dd>
            </div>
          </dl>

          {fixable > 0 && (
            <p className="text-secondary small mb-3">
              The rest need you: hats with no colorway are listed first and
              link straight to their edit form. Adding a colorway there lets
              that hat be priced against its own product instead of its line.
            </p>
          )}

          <ul className="hr-sd-groups">
            {groups.map(g => (
              <li key={`${g.resale_price}-${g.source ?? ''}`}>
                <div className="hr-sd-group-head">
                  <span className="hr-sd-group-price font-mono">
                    ${g.resale_price.toFixed(2)}
                  </span>
                  <span className="text-secondary small">{plural(g.hat_count, 'hat')}</span>
                </div>
                {g.source && (
                  <div className="hr-sd-legend">{g.source}</div>
                )}
                {g.missing_colorway > 0 && (
                  <div className="text-secondary small">
                    {g.missing_colorway} of these have no colorway recorded —
                    adding one lets that hat be priced against its own product.
                  </div>
                )}
                <div className="small hr-sd-group-hats">
                  {/* Each hat carries its own label, so nothing is indexed
                      against a second array that can fall out of step. A hat
                      with no case has no display_id — normal for a
                      room-stored one — and is named the way every other
                      screen names it (`hatName`). */}
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
                        {hatName(h)}
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
            <div className="hr-sd-legend mt-2">
              * no colorway recorded
            </div>
          )}
        </>
      )}
    </Panel>
  );
}
