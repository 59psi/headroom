/**
 * What the collection cost, what it's worth, and — the part that used to be
 * missing — how that second number is arrived at.
 *
 * The arithmetic lives in `lib/valuation`; this page is presentation plus the
 * explanation of the method. See that module for why the old "Est. resale"
 * figure was overstated and why its caption described a calculation that was
 * mostly not running.
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { listAllHats, listDisposedHats } from '../api/hats';
import { listCases } from '../api/cases';
import { BarList, ChartCard, StatTiles, StatTilesSkeleton } from '../components/charts/Charts';
import { PageHeader } from '../components/ui/PageHeader';
import { Panel } from '../components/ui/Panel';
import { Skeleton } from '../components/ui/Skeleton';
import {
  BASIS_LABEL, CASH_PAYOUT, CREDIT_PAYOUT, RETAIL_RETENTION,
  costOf, money, realizedTotals, valueCases, valueCollection, valueHat,
  type ValueBasis, CONDITION_LABEL,
} from '../lib/valuation';
import type { HatRead } from '../types';
import { RankedHatList } from '../components/hats/RankedHatList';

interface Bucket {
  key: string;
  label: string;
  count: number;
  paid: number;
  paidCount: number;
  value: number;
  valuedCount: number;
}

function bucketize(
  hats: HatRead[],
  keyFn: (h: HatRead) => string | null,
  labelFn: (k: string) => string = k => k,
): Bucket[] {
  const map = new Map<string, Bucket>();
  for (const h of hats) {
    const k = keyFn(h);
    if (!k) continue;
    const bucket = map.get(k) ?? {
      key: k, label: labelFn(k), count: 0, paid: 0, paidCount: 0, value: 0, valuedCount: 0,
    };
    bucket.count += 1;
    const paid = costOf(h);
    if (paid != null) { bucket.paid += paid; bucket.paidCount += 1; }
    const { value } = valueHat(h);
    if (value != null) { bucket.value += value; bucket.valuedCount += 1; }
    map.set(k, bucket);
  }
  return Array.from(map.values()).sort((a, b) => b.value - a.value || b.count - a.count);
}

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
    <ChartCard title={title}>
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
    </ChartCard>
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
  const hatsQ = useQuery({ queryKey: ['hats'], queryFn: listAllHats });
  const disposedQ = useQuery({ queryKey: ['hats', 'disposed'], queryFn: listDisposedHats });

  const hats = useMemo(() => hatsQ.data ?? [], [hatsQ.data]);
  const disposed = useMemo(() => disposedQ.data ?? [], [disposedQ.data]);

  const totals = useMemo(() => valueCollection(hats), [hats]);
  // The cases are part of the collection too — a melin travel case is $49 and
  // there are dozens, so leaving them out understated the total by four
  // figures, silently.
  const casesQ = useQuery({ queryKey: ['cases'], queryFn: listCases });
  const caseValue = useMemo(() => valueCases(casesQ.data ?? []), [casesQ.data]);
  const realized = useMemo(() => realizedTotals(disposed), [disposed]);

  const basisRows = useMemo(() => {
    const order: ValueBasis[] = ['manual', 'comp', 'retail', 'category', 'none'];
    return order
      .map(b => ({
        label: BASIS_LABEL[b],
        value: totals.byBasis[b].count,
        display: b === 'none'
          ? `${totals.byBasis[b].count} hats · not counted`
          : `${totals.byBasis[b].count} hats · ${money(totals.byBasis[b].total)}`,
      }))
      .filter(r => r.value > 0);
  }, [totals]);

  const missingCost = useMemo(
    () => hats.filter(h => costOf(h) == null).slice(0, 10),
    [hats],
  );

  const buckets = useMemo(() => ({
    condition: bucketize(hats, h => h.condition, k => CONDITION_LABEL[k] ?? k),
    brand: bucketize(hats, h => h.brand),
    style: bucketize(hats, h => h.style, k => k.replace(/_/g, ' ')),
    room: bucketize(hats, h => h.room_name),
  }), [hats]);

  const topValued = useMemo(
    () => [...hats]
      .filter(h => valueHat(h).value != null)
      .sort((a, b) => (valueHat(b).value ?? 0) - (valueHat(a).value ?? 0))
      .slice(0, 10),
    [hats],
  );

  const neglected = useMemo(
    () => [...hats]
      .sort((a, b) => ((a.date_last_worn ?? '0000') < (b.date_last_worn ?? '0000') ? -1 : 1))
      .slice(0, 5),
    [hats],
  );

  // A failed fetch must not render as an empty collection. `?? []` turns a
  // 500 or a dropped connection into "$0 across 0 hats", which is a confident
  // wrong answer — the exact thing `valueHat` returns `null` rather than 0 to
  // avoid. Errors are shown, not averaged in.
  if (hatsQ.isError || disposedQ.isError || casesQ.isError) {
    const retrying = hatsQ.isFetching || disposedQ.isFetching || casesQ.isFetching;
    return (
      <>
        <PageHead />
        <div className="alert alert-danger hr-cp-error" role="alert">
          <span>
            Couldn&rsquo;t load the collection, so no totals are shown — a partial
            valuation would be worse than none.
          </span>
          <button
            type="button"
            className="btn btn-sm btn-outline-secondary"
            onClick={() => { void hatsQ.refetch(); void disposedQ.refetch(); void casesQ.refetch(); }}
            disabled={retrying}
          >{retrying ? 'Retrying…' : 'Try again'}</button>
        </div>
      </>
    );
  }
  // All three, not just the hats: rendering before the cases or the disposed
  // hats arrive showed a total without its cases line, then grew one — a
  // figure that changes under you is the same confident wrong answer as the
  // error case above, only briefer.
  if (hatsQ.isLoading || disposedQ.isLoading || casesQ.isLoading) {
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

  return (
    <>
      <PageHead />

      <Panel title="Collection totals" featured>
        <StatTiles tiles={[
          {
            label: 'Paid',
            value: money(totals.spentTotal),
            tone: 'purple',
            sub: `${totals.spentCount} of ${totals.total} hats priced`,
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
                + {caseValue.count} case{caseValue.count === 1 ? '' : 's'} at
                replacement cost
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
      <ChartCard
        title="How the sale estimate is worked out"
        subtitle="Each hat uses the best signal it has. Stronger bases first."
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
                .map(([k, v]) => `${CONDITION_LABEL[k] ?? k} ${Math.round(v * 100)}%`)
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
        <BarList data={basisRows} colorize />
      </ChartCard>

      <ChartCard
        title="If you sold it all on melinrecap"
        subtitle="The market value above is gross. This is what would actually reach you."
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
      </ChartCard>

      {/* ===== Price paid ===== */}
      <ChartCard
        title="What you've paid"
        subtitle={
          totals.costUnknown > 0
            ? <>{totals.costUnknown} hat{totals.costUnknown === 1 ? '' : 's'} still
               have no purchase price. Import your order history from Settings, or
               set one on a hat's edit page.</>
            : <>Every hat has a purchase price on record.</>
        }
        action={
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
      </ChartCard>

      <div className="hr-cp-grid">
        <BucketTable title="By condition" column="Condition" buckets={buckets.condition} />
        <BucketTable title="By brand" column="Brand" buckets={buckets.brand} />
        <BucketTable title="By style" column="Style" buckets={buckets.style} />
        <BucketTable title="By room" column="Room" buckets={buckets.room} />

        <ChartCard title="Most valuable">
          <RankedHatList
            hats={topValued}
            valueFor={h => money(valueHat(h).value ?? 0)}
            empty={(
              <p className="text-muted small mb-0">
                No hats have a value estimate yet. Add a Claude API key in{' '}
                <Link to="/settings?tab=analysis">Settings</Link> and analyze a photo, or enter
                prices by hand.
              </p>
            )}
          />
        </ChartCard>

        <ChartCard title="Wear rotation" subtitle="Longest since last worn — give these some sun.">
          <RankedHatList
            hats={neglected}
            numbered={false}
            valueTone="muted"
            valueFor={h => h.date_last_worn ?? 'never worn'}
          />
        </ChartCard>
      </div>
    </>
  );
}
