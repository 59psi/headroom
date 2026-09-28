/**
 * What the collection cost, what it's worth, and — the part that used to be
 * missing — how that second number is arrived at.
 *
 * The arithmetic lives in `lib/valuation` and the roll-ups over it in
 * `lib/collectionViews`, shared with the Stats page; this page is
 * presentation plus the explanation of the method. See `lib/valuation` for why
 * the old "Est. resale" figure was overstated and why its caption described a
 * calculation that was mostly not running.
 */
import { useMemo } from 'react';
import { Link } from 'react-router';
import { BarList, StatTiles, StatTilesSkeleton } from '../components/charts/Charts';
import { LoadError } from '../components/common/LoadError';
import { PageHeader } from '../components/ui/PageHeader';
import { Panel } from '../components/ui/Panel';
import { Skeleton } from '../components/ui/Skeleton';
import {
  BASIS_LABEL, CASH_PAYOUT, CREDIT_PAYOUT, RETAIL_RETENTION,
  costOf, money, realizedTotals, valueCases, valueCollection, valueHat,
} from '../lib/valuation';
import { basisRows, bucketize, topValued, type Bucket } from '../lib/collectionViews';
import { useCollection } from '../lib/useCollection';
import { useHatLabels } from '../lib/labels';
import { plural } from '../lib/format';
import { RankedHatList } from '../components/hats/RankedHatList';

/**
 * One breakdown as a small table: what, how many, paid, worth.
 *
 * A table rather than the stacked "paid $x / worth $y" rows it replaced, so
 * the figures line up in columns and "which brand is worth the most" is read
 * down one edge instead of hunted for row by row. `—` where no hat in the
 * bucket has that figure, never `$0`.
 */
function BucketTable({ title, column, buckets }: { title: string; column: string; buckets: Bucket[] }) {
  if (buckets.length === 0) return null;
  return (
    <Panel title={title}>
      <table className="hr-cp-table">
        <thead>
          <tr>
            <th scope="col">{column}</th>
            <th scope="col" className="hr-cp-col-num">Hats</th>
            <th scope="col" className="hr-cp-col-money">Paid</th>
            <th scope="col" className="hr-cp-col-money">Worth</th>
          </tr>
        </thead>
        <tbody>
          {buckets.map(b => (
            <tr key={b.key}>
              <th scope="row"><span className="hr-cp-table-label" title={b.label}>{b.label}</span></th>
              <td className="hr-cp-col-num">{b.count}</td>
              <td className="hr-cp-col-money hr-cp-fig-paid">{b.paidCount > 0 ? money(b.paid) : '—'}</td>
              <td className="hr-cp-col-money hr-cp-fig-worth">{b.valuedCount > 0 ? money(b.value) : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function PageHead() {
  return (
    <PageHeader
      title="Valuation"
      actions={
        <>
          <Link to="/stats" className="btn btn-outline-secondary btn-sm">Stats →</Link>
          <Link to="/" className="btn btn-outline-secondary btn-sm">← Home</Link>
        </>
      }
    />
  );
}

export function ValuationPage() {
  const collection = useCollection();
  const { hats, disposed, cases } = collection;
  const labels = useHatLabels();

  const totals = useMemo(() => valueCollection(hats), [hats]);
  // The cases are part of the collection too — a melin travel case is $49 and
  // there are dozens, so leaving them out understated the total by four
  // figures, silently.
  const caseValue = useMemo(() => valueCases(cases), [cases]);
  const realized = useMemo(() => realizedTotals(disposed), [disposed]);
  const bases = useMemo(() => basisRows(totals), [totals]);

  const missingCost = useMemo(
    () => hats.filter(h => costOf(h) == null).slice(0, 10),
    [hats],
  );

  const mostValuable = useMemo(() => topValued(hats), [hats]);

  const neglected = useMemo(
    () => [...hats]
      .sort((a, b) => ((a.date_last_worn ?? '0000') < (b.date_last_worn ?? '0000') ? -1 : 1))
      .slice(0, 5),
    [hats],
  );

  // A failed fetch must not render as an empty collection — see
  // `useCollection`. Errors are shown, not averaged in.
  if (collection.failed) {
    return (
      <>
        <PageHead />
        <LoadError
          what="Couldn’t load the collection, so no totals are shown — a partial valuation would be worse than none."
          queries={collection.queries}
        />
      </>
    );
  }
  // All three, not just the hats: rendering before the cases or the disposed
  // hats arrive showed a total without its cases line, then grew one — a
  // figure that changes under you is the same confident wrong answer as the
  // error case above, only briefer.
  if (collection.loading) {
    return (
      <>
        <PageHead />
        <Panel title="Collection totals" featured>
          <StatTilesSkeleton count={4} label="Loading the valuation…" />
        </Panel>
        <Panel title="How the sale estimate is worked out">
          <Skeleton lines={3} />
        </Panel>
      </>
    );
  }

  const avgPaid = totals.spentCount > 0 ? totals.spentTotal / totals.spentCount : 0;
  // Style and condition by the server's labels ("A-Game"), the words every
  // other screen uses — the style column printed "a game". A plain
  // computation rather than a memo: the label functions are new each render,
  // so a memo keyed on them would recompute anyway.
  const buckets = {
    condition: bucketize(hats, h => h.condition, labels.condition),
    brand: bucketize(hats, h => h.brand),
    style: bucketize(hats, h => h.style, labels.style),
    room: bucketize(hats, h => h.room_name),
  };

  return (
    <>
      <PageHead />

      <Panel title="Collection totals" featured>
        <StatTiles tiles={[
          {
            label: 'Paid',
            value: money(totals.spentTotal),
            tone: 'purple',
            sub: `${totals.spentCount} of ${plural(totals.total, 'hat')} priced`,
          },
          {
            label: 'Retail value',
            value: money(totals.retailTotal),
            tone: 'cyan',
            sub: `${totals.retailCount} appraised`,
          },
          {
            label: 'Est. sale value',
            value: money(totals.marketTotal),
            tone: 'pink',
            sub: totals.retentionPct != null ? `${totals.retentionPct}% of retail` : undefined,
          },
          {
            label: 'vs. paid',
            value: totals.unrealizedGain != null
              ? `${totals.unrealizedGain >= 0 ? '+' : '−'}${money(Math.abs(totals.unrealizedGain))}`
              : '—',
            tone: totals.unrealizedGain != null && totals.unrealizedGain >= 0 ? 'cyan' : 'muted',
            sub: totals.unrealizedGain != null
              ? 'hats with both figures'
              : 'needs purchase prices',
          },
        ]} />
        {totals.unvalued > 0 && (
          <p className="hr-cp-note">
            {totals.unvalued} hat{totals.unvalued === 1 ? ' has' : 's have'} no
            price data at all and {totals.unvalued === 1 ? 'is' : 'are'} left out
            of every figure above rather than counted as $0.
          </p>
        )}

        {/* Kept as its own line rather than folded into the tiles above:
            cases are valued at replacement cost, hats at market, and adding
            two different KINDS of number together silently would make every
            comparison on this page — retention, gain, cost per hat — wrong
            in a way nobody could see. */}
        {caseValue.count > 0 && (
          <div className="hr-case-total mt-3">
            <div className="hr-cp-case-line">
              <span className="text-secondary small">
                + {plural(caseValue.count, 'case')} at replacement cost
              </span>
              <span className="font-mono">{money(caseValue.retailTotal)}</span>
            </div>
            <div className="hr-cp-case-line mt-1">
              <strong className="small">Everything, together</strong>
              <strong className="font-mono hr-cp-case-grand">
                {money(totals.marketTotal + caseValue.retailTotal)}
              </strong>
            </div>
            <p className="hr-cp-note mt-1">
              Hats at estimated sale value plus cases at what they cost to
              replace — cases have no resale market to price them against.
            </p>
          </div>
        )}
      </Panel>

      {/* ===== The method, stated =====
          The chart of bases stays in view; the four paragraphs behind it are
          one tap away rather than a wall of text between the totals and the
          rest of the page. Nothing was cut — this is the only place the
          method is written down. */}
      <Panel
        title="How the sale estimate is worked out"
        description="Each hat uses the best signal it has. Stronger bases first."
        helpLabel="The method in detail"
        help={
          <>
            <p className="mb-2">
              <strong>On melinrecap the listed price is the sale price.</strong>{' '}
              It's a fixed-price marketplace with automatic drops — a buyer clicks
              buy at the number shown — so nothing is discounted off it. What
              makes a median comparable is <em>filtering</em>: each hat is priced
              against live listings matching its own model, condition and size,
              narrowing to something broader only when the market has too few of
              the exact thing.
            </p>
            <p className="mb-2">
              This replaced a pair of invented factors — a 15% ask-to-sale
              haircut and a guessed condition multiplier. Measured against 706
              live listings the guesses were wrong (new-without-tags sells at 95%
              of new-with-tags, not 92%; worn at 82%, not 78%), and they were
              never needed when the real number is in the feed.
            </p>
            <p className="mb-2">
              With no listings to compare against, the estimate falls back to a
              share of new retail: {Object.entries(RETAIL_RETENTION)
                .map(([k, v]) => `${labels.condition(k)} ${Math.round(v * 100)}%`)
                .join(' · ')}.
            </p>
            <p className="mb-0">
              <strong>{BASIS_LABEL.category}</strong> is the weak one: no listings
              matched the model, so it borrows the median across the whole style
              category — the going rate for a hat of that shape, not a valuation
              of this hat.
            </p>
          </>
        }
      >
        <BarList data={bases} colorize />
      </Panel>

      <Panel
        title="If you sold it all on melinrecap"
        description="The market value above is gross. This is what would actually reach you."
      >
        <StatTiles tiles={[
          {
            label: 'Market value',
            value: money(totals.marketTotal),
            tone: 'muted',
            sub: 'what buyers pay',
          },
          {
            label: 'Cash to you',
            value: money(totals.marketTotal * CASH_PAYOUT),
            tone: 'pink',
            sub: `${Math.round(CASH_PAYOUT * 100)}% payout`,
          },
          {
            label: 'As brand credit',
            value: money(totals.marketTotal * CREDIT_PAYOUT),
            tone: 'cyan',
            sub: `${Math.round(CREDIT_PAYOUT * 100)}% payout`,
          },
          {
            label: 'Credit vs cash',
            value: `+${money(totals.marketTotal * (CREDIT_PAYOUT - CASH_PAYOUT))}`,
            tone: 'purple',
            sub: 'spendable at melin only',
          },
        ]} />
        <p className="hr-cp-note">
          Rates come from the marketplace itself — every listing carries them.
          Selling the whole collection at once is not a realistic event; this is
          a scale, not a plan.
        </p>
      </Panel>

      {/* ===== Price paid ===== */}
      <Panel
        title="What you've paid"
        description={
          totals.costUnknown > 0
            ? <>{plural(totals.costUnknown, 'hat')} still{' '}
               {totals.costUnknown === 1 ? 'has' : 'have'} no purchase price.
               Import your order history from Settings, or set one on a hat's
               edit page.</>
            : <>Every hat has a purchase price on record.</>
        }
        actions={
          totals.costUnknown > 0
            ? <Link to="/settings?tab=data" className="btn btn-outline-secondary btn-sm">Import prices</Link>
            : undefined
        }
      >
        <StatTiles tiles={[
          { label: 'Total paid', value: money(totals.spentTotal), tone: 'purple' },
          { label: 'Average', value: totals.spentCount > 0 ? money(avgPaid) : '—', tone: 'muted' },
          {
            label: 'Priced',
            value: `${totals.spentCount}/${totals.total}`,
            tone: 'cyan',
            sub: `${Math.round((totals.spentCount / Math.max(totals.total, 1)) * 100)}% covered`,
          },
          {
            label: 'Sold for',
            value: money(realized.proceeds),
            tone: 'pink',
            sub: realized.netGain != null
              ? `${realized.netGain >= 0 ? '+' : '−'}${money(Math.abs(realized.netGain))} vs cost`
              : `${realized.sold} sold`,
          },
        ]} />
        {missingCost.length > 0 && (
          <>
            <div className="hr-eyebrow mt-3">Missing a price</div>
            <RankedHatList hats={missingCost} valueFor={() => 'set price'} />
            {totals.costUnknown > missingCost.length && (
              <p className="hr-cp-note mt-2">
                …and {totals.costUnknown - missingCost.length} more.
              </p>
            )}
          </>
        )}
      </Panel>

      <div className="hr-cp-grid">
        <BucketTable title="By condition" column="Condition" buckets={buckets.condition} />
        <BucketTable title="By brand" column="Brand" buckets={buckets.brand} />
        <BucketTable title="By style" column="Style" buckets={buckets.style} />
        <BucketTable title="By room" column="Room" buckets={buckets.room} />

        <Panel title="Most valuable">
          <RankedHatList
            hats={mostValuable}
            valueFor={h => money(valueHat(h).value ?? 0)}
            empty={(
              <p className="text-muted small mb-0">
                No hats have a value estimate yet. Add a Claude API key in{' '}
                <Link to="/settings?tab=analysis">Settings</Link> and analyze a photo, or enter
                prices by hand.
              </p>
            )}
          />
        </Panel>

        <Panel title="Wear rotation" description="Longest since last worn — give these some sun.">
          <RankedHatList
            hats={neglected}
            numbered={false}
            valueTone="muted"
            valueFor={h => h.date_last_worn ?? 'never worn'}
          />
        </Panel>
      </div>
    </>
  );
}
