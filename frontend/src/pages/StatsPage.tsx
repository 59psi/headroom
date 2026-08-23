/**
 * The whole collection as numbers.
 *
 * Everything here is derived client-side from the hat list the rest of the app
 * already loads, so opening this page costs one cached query rather than a new
 * reporting endpoint. That also means every figure is computed by the same
 * `lib/valuation` rule the home page and the valuation page use — the three
 * hand-rolled copies that preceded it had already drifted apart.
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { listAllHats, listDisposedHats } from '../api/hats';
import { listCases } from '../api/cases';
import { listRooms } from '../api/rooms';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import {
  BarList, ChartCard, Donut, StatTiles, TimeSeries,
  type ChartDatum, type TimePoint,
} from '../components/charts/Charts';
import {
  BASIS_LABEL, money, moneyPrecise, realizedTotals, valueCases, valueCollection, valueHat,
  costOf, type ValueBasis,
  CONDITION_LABEL,
} from '../lib/valuation';
import { tileSrc } from '../lib/photo';
import type { CaseRead, HatRead } from '../types';

const CONDITION_COLOR: Record<string, string> = {
  new_with_tags: 'var(--neon-cyan)',
  new: 'var(--neon-purple)',
  worn: 'var(--neon-orange)',
};

const prettify = (s: string) => s.replace(/_/g, ' ');

/** Count hats by a key, drop the ones with no value for it, biggest first. */
function countBy(
  hats: HatRead[],
  keyFn: (h: HatRead) => string | null | undefined,
  limit?: number,
): ChartDatum[] {
  const counts = new Map<string, number>();
  for (const h of hats) {
    const k = keyFn(h);
    if (!k) continue;
    counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  const rows = Array.from(counts, ([label, value]) => ({ label, value }))
    .sort((a, b) => b.value - a.value || a.label.localeCompare(b.label));
  return limit ? rows.slice(0, limit) : rows;
}

/** Sum estimated sale value by a key. */
function valueBy(
  hats: HatRead[],
  keyFn: (h: HatRead) => string | null | undefined,
  limit?: number,
): ChartDatum[] {
  const totals = new Map<string, { total: number; count: number }>();
  for (const h of hats) {
    const k = keyFn(h);
    if (!k) continue;
    const { value } = valueHat(h);
    if (value == null) continue;
    const prev = totals.get(k) ?? { total: 0, count: 0 };
    totals.set(k, { total: prev.total + value, count: prev.count + 1 });
  }
  const rows = Array.from(totals, ([label, v]) => ({
    label,
    value: v.total,
    display: `${money(v.total)} · ${v.count}`,
  })).sort((a, b) => b.value - a.value);
  return limit ? rows.slice(0, limit) : rows;
}

/**
 * Bucket dated events by month, INCLUDING months where nothing happened.
 *
 * The empty months are the point — a gap is a fact about the collection, and a
 * chart that omits them turns a six-month pause into an unbroken run.
 */
function monthlySeries(
  entries: Array<{ date: string; amount: number }>,
): TimePoint[] {
  if (!entries.length) return [];
  const buckets = new Map<string, number>();
  for (const e of entries) {
    const key = e.date.slice(0, 7); // "YYYY-MM"
    buckets.set(key, (buckets.get(key) ?? 0) + e.amount);
  }
  const keys = Array.from(buckets.keys()).sort();
  const [firstY, firstM] = keys[0].split('-').map(Number);
  const [lastY, lastM] = keys[keys.length - 1].split('-').map(Number);

  const out: TimePoint[] = [];
  // Walk with a Date so the year rollover is the calendar's problem, not a
  // modulo expression's.
  for (
    let d = new Date(Date.UTC(firstY, firstM - 1, 1));
    d <= new Date(Date.UTC(lastY, lastM - 1, 1));
    d.setUTCMonth(d.getUTCMonth() + 1)
  ) {
    const key = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
    out.push({
      key,
      label: d.toLocaleDateString(undefined, { month: 'short', year: '2-digit', timeZone: 'UTC' }),
      value: buckets.get(key) ?? 0,
    });
  }
  return out;
}

/** A ranked hat list with photo — used for every "top N" block. */
function HatRank({
  hats,
  valueFor,
  emptyText,
}: {
  hats: HatRead[];
  valueFor: (h: HatRead) => string;
  emptyText: string;
}) {
  if (!hats.length) return <p className="text-muted small mb-0">{emptyText}</p>;
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
              {h.brand || prettify(h.style)}{h.model_name && ` · ${h.model_name}`}
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

export function StatsPage() {
  const hatsQ = useQuery({ queryKey: ['hats'], queryFn: listAllHats });
  const disposedQ = useQuery({ queryKey: ['hats', 'disposed'], queryFn: listDisposedHats });
  const casesQ = useQuery({ queryKey: ['cases'], queryFn: listCases });
  const roomsQ = useQuery({ queryKey: ['rooms'], queryFn: listRooms });

  const hats = useMemo(() => hatsQ.data ?? [], [hatsQ.data]);
  const disposed = useMemo(() => disposedQ.data ?? [], [disposedQ.data]);
  const cases = useMemo(() => casesQ.data ?? [], [casesQ.data]);

  const valuation = useMemo(() => valueCollection(hats), [hats]);
  // Cases are part of the collection: dozens of them at $49 each. Shown as
  // their own tile rather than folded into the hat figures — they are valued
  // at replacement cost, where hats are valued at market.
  const caseValue = useMemo(() => valueCases(casesQ.data ?? []), [casesQ.data]);
  const realized = useMemo(() => realizedTotals(disposed), [disposed]);

  const wear = useMemo(() => {
    const totalWears = hats.reduce((s, h) => s + (h.wear_count ?? 0), 0);
    const neverWorn = hats.filter(h => (h.wear_count ?? 0) === 0).length;
    const mostWorn = [...hats]
      .filter(h => (h.wear_count ?? 0) > 0)
      .sort((a, b) => (b.wear_count ?? 0) - (a.wear_count ?? 0))
      .slice(0, 10);
    // Cost per wear only means anything where BOTH numbers are on record —
    // a hat with no purchase price would otherwise show as free.
    const costPerWear = hats
      .map(h => {
        const cost = costOf(h);
        const wears = h.wear_count ?? 0;
        return cost != null && wears > 0 ? { h, cpw: cost / wears } : null;
      })
      .filter((x): x is { h: HatRead; cpw: number } => x !== null)
      .sort((a, b) => a.cpw - b.cpw);
    return { totalWears, neverWorn, mostWorn, costPerWear };
  }, [hats]);

  const timelines = useMemo(() => {
    // `purchased_at` is the real acquisition date and comes from order
    // history; `created_at` is only when the photo was uploaded. Prefer the
    // former, fall back to the latter so a hat still appears somewhere.
    const acquired = hats
      .map(h => h.purchased_at ?? h.created_at)
      .filter(Boolean)
      .map(date => ({ date: date as string, amount: 1 }));
    const spend = hats
      .filter(h => costOf(h) != null && h.purchased_at)
      .map(h => ({ date: h.purchased_at as string, amount: h.purchase_price as number }));
    return { acquired: monthlySeries(acquired), spend: monthlySeries(spend) };
  }, [hats]);

  const colors = useMemo(() => {
    const counts = new Map<string, { count: number; hex: string }>();
    for (const h of hats) {
      // One vote per hat per colour name, so a hat tagged with three shades of
      // blue doesn't outvote three separate blue hats.
      const seen = new Set<string>();
      for (const c of h.colors ?? []) {
        const name = c.general_color || c.color_name;
        if (!name || seen.has(name)) continue;
        seen.add(name);
        const prev = counts.get(name);
        counts.set(name, { count: (prev?.count ?? 0) + 1, hex: prev?.hex ?? c.hex_value });
      }
    }
    return Array.from(counts, ([label, v]) => ({
      label,
      value: v.count,
      color: v.hex,
      href: `/search?color=${encodeURIComponent(v.hex)}`,
    }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 14);
  }, [hats]);

  const caseFill = useMemo(() => {
    // Server-supplied, not re-derived: the defaults live in `services/capacity`
    // and a second copy here went stale the moment regular capacity became 3.
    const capacityOf = (c: CaseRead) => c.nominal_capacity;
    return [...cases]
      .map(c => ({
        label: `${c.display_id} · ${c.room_name}`,
        value: c.hat_count,
        display: `${c.hat_count}/${capacityOf(c)}`,
        href: `/cases/${c.display_id}`,
        color: c.overfull
          ? 'var(--neon-orange)'
          : c.hat_count >= capacityOf(c) ? 'var(--neon-pink)' : 'var(--neon-cyan)',
      }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 12);
  }, [cases]);

  const basisRows: ChartDatum[] = useMemo(() => {
    const order: ValueBasis[] = ['manual', 'comp', 'retail', 'category', 'none'];
    return order
      .map(b => ({
        label: BASIS_LABEL[b],
        value: valuation.byBasis[b].count,
        display: b === 'none'
          ? `${valuation.byBasis[b].count} hats`
          : `${valuation.byBasis[b].count} hats · ${money(valuation.byBasis[b].total)}`,
      }))
      .filter(r => r.value > 0);
  }, [valuation]);

  if (hatsQ.isLoading || casesQ.isLoading) return <LoadingSpinner />;

  const conditionData: ChartDatum[] = ['new_with_tags', 'new', 'worn']
    .map(k => ({
      label: CONDITION_LABEL[k],
      value: hats.filter(h => h.condition === k).length,
      color: CONDITION_COLOR[k],
    }))
    .filter(d => d.value > 0);

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3 gap-2 flex-wrap">
        <h1>Stats</h1>
        <div className="d-flex gap-2">
          <Link to="/valuation" className="btn btn-outline-primary btn-sm">Valuation →</Link>
          <Link to="/" className="btn btn-outline-secondary btn-sm">← Home</Link>
        </div>
      </div>

      {/* ===== Totals ===== */}
      <ChartCard title="The collection">
        <StatTiles tiles={[
          { label: 'Hats', value: String(hats.length), tone: 'pink' },
          { label: 'Cases', value: String(cases.length), tone: 'cyan' },
          { label: 'Rooms', value: String(roomsQ.data?.length ?? 0), tone: 'purple' },
          {
            label: 'Total wears',
            value: wear.totalWears.toLocaleString(),
            tone: 'muted',
            sub: `${wear.neverWorn} never worn`,
          },
        ]} />
      </ChartCard>

      <ChartCard
        title="Money"
        subtitle={<>Sale value is estimated — <Link to="/valuation">how it's worked out</Link>.</>}
      >
        <StatTiles tiles={[
          {
            label: 'Paid',
            value: money(valuation.spentTotal),
            tone: 'purple',
            sub: `${valuation.spentCount} of ${valuation.total} hats priced`,
          },
          {
            label: 'Retail value',
            value: money(valuation.retailTotal),
            tone: 'cyan',
            sub: `${valuation.retailCount} appraised`,
          },
          {
            label: 'Est. sale value',
            value: money(valuation.marketTotal),
            tone: 'pink',
            sub: valuation.retentionPct != null ? `${valuation.retentionPct}% of retail` : undefined,
          },
          {
            label: 'Cases',
            value: money(caseValue.retailTotal),
            tone: 'cyan',
            sub: `${caseValue.count} at replacement cost`,
          },
          {
            label: 'Everything',
            value: money(valuation.marketTotal + caseValue.retailTotal),
            tone: 'pink',
            sub: 'hats + cases',
          },
          {
            label: 'Realized',
            value: money(realized.proceeds),
            tone: 'muted',
            sub: `${realized.sold} sold${realized.otherDisposals > 0 ? ` · ${realized.otherDisposals} other` : ''}`,
          },
        ]} />
      </ChartCard>

      {/* ===== Where the value estimate comes from ===== */}
      <ChartCard
        title="What the estimate rests on"
        subtitle="Each hat is valued from the best signal it has. Weaker bases are worth knowing about."
      >
        <BarList data={basisRows} colorize />
      </ChartCard>

      {/* ===== Composition ===== */}
      <ChartCard title="By condition">
        <Donut
          data={conditionData}
          centerValue={String(hats.length)}
          centerLabel="hats"
        />
      </ChartCard>

      <ChartCard title="By style">
        <BarList
          data={countBy(hats, h => prettify(h.style)).map(d => ({
            ...d,
            href: `/hats?style=${encodeURIComponent(d.label.replace(/ /g, '_'))}`,
          }))}
          colorize
        />
      </ChartCard>

      <ChartCard title="By size">
        <BarList data={countBy(hats, h => prettify(h.size))} colorize />
      </ChartCard>

      <ChartCard title="By brand" subtitle="Hats with no brand identified are left out.">
        <BarList data={countBy(hats, h => h.brand, 12)} colorize />
      </ChartCard>

      <ChartCard title="By construction" subtitle="Hats with no construction recorded are left out.">
        <BarList data={countBy(hats, h => h.construction, 12)} colorize />
      </ChartCard>

      <ChartCard title="Top colorways">
        <BarList data={countBy(hats, h => h.colorway, 12)} colorize />
      </ChartCard>

      <ChartCard title="Artist & collab series">
        <BarList
          data={countBy(hats, h => h.artist_series, 12)}
          emptyText="No collab or artist series recorded yet."
          colorize
        />
      </ChartCard>

      <ChartCard title="Colours" subtitle="One vote per hat per colour. Tap to search that shade.">
        <BarList data={colors} emptyText="No colours detected yet." />
      </ChartCard>

      {/* ===== Where it all lives ===== */}
      <ChartCard title="Hats by room">
        <BarList data={countBy(hats, h => h.room_name)} colorize />
      </ChartCard>

      <ChartCard title="Value by room">
        <BarList data={valueBy(hats, h => h.room_name)} colorize />
      </ChartCard>

      <ChartCard title="Fullest cases" subtitle="Full in pink, overfull in orange.">
        <BarList data={caseFill} emptyText="No cases yet." />
      </ChartCard>

      {/* ===== Over time ===== */}
      <ChartCard
        title="Hats acquired"
        subtitle="By purchase date where known, otherwise when the photo was added."
      >
        <TimeSeries points={timelines.acquired} />
      </ChartCard>

      <ChartCard
        title="Spend over time"
        subtitle={
          valuation.costUnknown > 0
            ? <>Only the {valuation.spentCount} hats with a recorded price and date. The cyan line is the running total.</>
            : <>The cyan line is the running total.</>
        }
      >
        <TimeSeries points={timelines.spend} cumulative />
      </ChartCard>

      {/* ===== Leaderboards ===== */}
      <ChartCard title="Most valuable">
        <HatRank
          hats={[...hats]
            .filter(h => valueHat(h).value != null)
            .sort((a, b) => (valueHat(b).value ?? 0) - (valueHat(a).value ?? 0))
            .slice(0, 10)}
          valueFor={h => money(valueHat(h).value ?? 0)}
          emptyText="No hats have a value estimate yet."
        />
      </ChartCard>

      <ChartCard title="Most expensive (paid)">
        <HatRank
          hats={[...hats]
            .filter(h => costOf(h) != null)
            .sort((a, b) => (costOf(b) ?? 0) - (costOf(a) ?? 0))
            .slice(0, 10)}
          valueFor={h => money(costOf(h) ?? 0)}
          emptyText="No purchase prices recorded yet."
        />
      </ChartCard>

      <ChartCard title="Most worn">
        <HatRank
          hats={wear.mostWorn}
          valueFor={h => `${h.wear_count}×`}
          emptyText="No wears logged yet — tap “Wearing this today” on a hat."
        />
      </ChartCard>

      <ChartCard
        title="Best cost per wear"
        subtitle="What you paid, divided by how often you've worn it. Needs both numbers."
      >
        <HatRank
          hats={wear.costPerWear.slice(0, 10).map(x => x.h)}
          valueFor={h => {
            const cost = costOf(h) ?? 0;
            return `${moneyPrecise(cost / (h.wear_count || 1))}/wear`;
          }}
          emptyText="Needs a purchase price and at least one logged wear."
        />
      </ChartCard>
    </>
  );
}
