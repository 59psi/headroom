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
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { BarList, ChartCard, StatTiles } from '../components/charts/Charts';
import {
  BASIS_LABEL, CASH_PAYOUT, CREDIT_PAYOUT, RETAIL_RETENTION,
  costOf, money, realizedTotals, valueCases, valueCollection, valueHat,
  type ValueBasis, CONDITION_LABEL,
} from '../lib/valuation';
import type { HatRead } from '../types';
import { tileSrc } from '../lib/photo';

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

function BucketTable({ title, buckets }: { title: string; buckets: Bucket[] }) {
  if (buckets.length === 0) return null;
  return (
    <ChartCard title={title}>
      {buckets.map(b => (
        <div key={b.key} className="hr-color-row" style={{ paddingTop: '0.5rem' }}>
          <div className="flex-grow-1" style={{ minWidth: 0 }}>
            <div
              className="fw-semibold"
              style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
            >{b.label}</div>
            <div className="text-muted small font-mono">
              {b.count} hat{b.count === 1 ? '' : 's'}
            </div>
          </div>
          <div className="text-end">
            <div className="font-mono small">
              <span className="text-secondary">paid </span>
              <span style={{ color: 'var(--neon-purple)' }}>
                {b.paidCount > 0 ? money(b.paid) : '—'}
              </span>
            </div>
            <div className="font-mono small">
              <span className="text-secondary">worth </span>
              <span style={{ color: 'var(--neon-pink)' }}>
                {b.valuedCount > 0 ? money(b.value) : '—'}
              </span>
            </div>
          </div>
        </div>
      ))}
    </ChartCard>
  );
}

function HatList({ hats, valueFor }: { hats: HatRead[]; valueFor: (h: HatRead) => string }) {
  return (
    <div>
      {hats.map((h, i) => (
        <Link
          key={h.id}
          to={`/hats/${h.id}`}
          className="hr-color-row text-decoration-none"
          style={{ paddingTop: '0.5rem' }}
        >
          <div className="font-mono fw-bold" style={{ color: 'var(--neon-purple)', minWidth: 22 }}>
            {i + 1}.
          </div>
          {h.photo_path ? (
            <img src={tileSrc(h)} alt="" className="hr-thumb flex-shrink-0" style={{ width: 40, height: 40 }} />
          ) : (
            <div className="rounded flex-shrink-0" style={{ width: 40, height: 40, background: 'rgba(0,0,0,0.3)' }} />
          )}
          <div className="flex-grow-1" style={{ minWidth: 0 }}>
            <div className="font-mono small" style={{ color: 'var(--neon-cyan)' }}>
              {h.display_id || `Hat #${h.id}`}
            </div>
            <div
              className="text-secondary small"
              style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
            >
              {h.brand || h.style.replace(/_/g, ' ')}{h.model_name && ` · ${h.model_name}`}
            </div>
          </div>
          <div className="font-mono fw-bold flex-shrink-0" style={{ color: 'var(--neon-pink)' }}>
            {valueFor(h)}
          </div>
        </Link>
      ))}
    </div>
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
    return (
      <div className="alert alert-danger" role="alert">
        Couldn&rsquo;t load the collection, so no totals are shown — a partial
        valuation would be worse than none. Reload to try again.
      </div>
    );
  }
  if (hatsQ.isLoading) return <LoadingSpinner />;

  const avgPaid = totals.spentCount > 0 ? totals.spentTotal / totals.spentCount : 0;

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3 gap-2 flex-wrap">
        <h1>Valuation</h1>
        <div className="d-flex gap-2">
          <Link to="/stats" className="btn btn-outline-primary btn-sm">Stats →</Link>
          <Link to="/" className="btn btn-outline-secondary btn-sm">← Home</Link>
        </div>
      </div>

      <div className="card hr-feature mb-3">
        <div className="card-body">
          <div className="card-title mb-2">Collection totals</div>
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
            <p className="text-muted small mb-0 mt-3" style={{ fontSize: '0.72rem' }}>
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
              <div className="d-flex justify-content-between align-items-baseline">
                <span className="text-secondary small">
                  + {caseValue.count} case{caseValue.count === 1 ? '' : 's'} at
                  replacement cost
                </span>
                <span className="font-mono">{money(caseValue.retailTotal)}</span>
              </div>
              <div className="d-flex justify-content-between align-items-baseline mt-1">
                <strong className="small">Everything, together</strong>
                <strong className="font-mono" style={{ color: 'var(--neon-cyan)' }}>
                  {money(totals.marketTotal + caseValue.retailTotal)}
                </strong>
              </div>
              <p className="text-muted mb-0 mt-1" style={{ fontSize: '0.72rem' }}>
                Hats at estimated sale value plus cases at what they cost to
                replace — cases have no resale market to price them against.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* ===== The method, stated ===== */}
      <ChartCard
        title="How the sale estimate is worked out"
        subtitle="Each hat uses the best signal it has. Stronger bases first."
      >
        <BarList data={basisRows} colorize />
        <div className="text-secondary small mt-3" style={{ fontSize: '0.78rem', lineHeight: 1.6 }}>
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
        </div>
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
        <p className="text-muted small mb-0 mt-3" style={{ fontSize: '0.72rem' }}>
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
            ? <Link to="/settings" className="btn btn-outline-primary btn-sm flex-shrink-0">Import</Link>
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
            <div className="hr-tier-label mt-3 mb-2">Missing a price</div>
            <HatList hats={missingCost} valueFor={() => 'set price'} />
            {totals.costUnknown > missingCost.length && (
              <p className="text-muted small mb-0 mt-2">
                …and {totals.costUnknown - missingCost.length} more.
              </p>
            )}
          </>
        )}
      </ChartCard>

      <BucketTable title="By condition" buckets={buckets.condition} />
      <BucketTable title="By brand" buckets={buckets.brand} />
      <BucketTable title="By style" buckets={buckets.style} />
      <BucketTable title="By room" buckets={buckets.room} />

      <ChartCard title="Most valuable">
        {topValued.length ? (
          <HatList hats={topValued} valueFor={h => money(valueHat(h).value ?? 0)} />
        ) : (
          <p className="text-muted small mb-0">
            No hats have a value estimate yet. Add a Claude API key in{' '}
            <Link to="/settings">Settings</Link> and analyze a photo, or enter
            prices by hand.
          </p>
        )}
      </ChartCard>

      <ChartCard title="Wear rotation" subtitle="Longest since last worn — give these some sun.">
        <div>
          {neglected.map(h => (
            <Link
              key={h.id}
              to={`/hats/${h.id}`}
              className="hr-color-row text-decoration-none"
              style={{ paddingTop: '0.5rem' }}
            >
              {h.photo_path ? (
                <img src={tileSrc(h)} alt="" className="hr-thumb flex-shrink-0" style={{ width: 40, height: 40 }} />
              ) : (
                <div className="rounded flex-shrink-0" style={{ width: 40, height: 40, background: 'rgba(0,0,0,0.3)' }} />
              )}
              <div className="flex-grow-1" style={{ minWidth: 0 }}>
                <div className="font-mono small" style={{ color: 'var(--neon-cyan)' }}>
                  {h.display_id || `Hat #${h.id}`}
                </div>
                <div className="text-secondary small">
                  {h.brand || h.style.replace(/_/g, ' ')}{h.model_name && ` · ${h.model_name}`}
                </div>
              </div>
              <div className="text-secondary small font-mono flex-shrink-0">
                {h.date_last_worn ?? 'never worn'}
              </div>
            </Link>
          ))}
        </div>
      </ChartCard>
    </>
  );
}
