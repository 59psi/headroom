/**
 * The whole collection as numbers.
 *
 * Everything here is derived client-side from the hat list the rest of the app
 * already loads, so opening this page costs one cached query rather than a new
 * reporting endpoint. That also means every figure is computed by the same
 * `lib/valuation` rule the home page and the valuation page use — the three
 * hand-rolled copies that preceded it had already drifted apart.
 */
import { useMemo, type MouseEvent, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { listAllHats, listDisposedHats } from '../api/hats';
import { listCases } from '../api/cases';
import { listRooms } from '../api/rooms';
import {
  BarList, ChartCard, Donut, StatTiles, StatTilesSkeleton, TimeSeries,
  type ChartDatum, type TimePoint,
} from '../components/charts/Charts';
import { Panel } from '../components/ui/Panel';
import {
  BASIS_LABEL, money, moneyPrecise, realizedTotals, valueCases, valueCollection, valueHat,
  costOf, type ValueBasis,
  CONDITION_LABEL,
} from '../lib/valuation';
import { RankedHatList } from '../components/hats/RankedHatList';
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

/**
 * The page's sections, in order. Twenty-odd cards in one column was a long
 * way to scroll for "which room is fullest"; grouped under five headings with
 * a jump bar at the top, each answer is one tap from the top of the page.
 */
const SECTIONS = [
  { id: 'stats-overview', label: 'Overview' },
  { id: 'stats-composition', label: 'Composition' },
  { id: 'stats-where', label: 'Where it lives' },
  { id: 'stats-time', label: 'Over time' },
  { id: 'stats-leaders', label: 'Leaderboards' },
] as const;

type SectionId = (typeof SECTIONS)[number]['id'];

/**
 * Scroll to a section and move focus to its heading.
 *
 * Handled here rather than left to the browser's own `#hash` jump: the router
 * would see each jump as a navigation (a history entry per tap, so Back walks
 * the page's sections before it leaves the page), and a hash jump does not
 * move keyboard focus, so Tab would carry on from the jump bar rather than
 * from the section just scrolled to.
 */
function jumpTo(e: MouseEvent, id: SectionId) {
  e.preventDefault();
  const heading = document.getElementById(`${id}-title`);
  if (!heading) return;
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  heading.scrollIntoView?.({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
  heading.focus({ preventScroll: true });
}

function Section({ id, title, children }: { id: SectionId; title: string; children: ReactNode }) {
  return (
    <section className="hr-cp-section" aria-labelledby={`${id}-title`}>
      {/* tabIndex -1: focusable by `jumpTo`, not a Tab stop. */}
      <h2 id={`${id}-title`} className="hr-cp-section-title" tabIndex={-1}>{title}</h2>
      <div className="hr-cp-grid">{children}</div>
    </section>
  );
}

function PageHead() {
  return (
    <header className="hr-cp-head">
      <div className="hr-cp-head-title">
        <h1>Stats</h1>
      </div>
      <div className="hr-cp-head-actions">
        <Link to="/valuation" className="btn btn-outline-secondary btn-sm">Valuation →</Link>
        <Link to="/" className="btn btn-outline-secondary btn-sm">← Home</Link>
      </div>
    </header>
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
      // One vote per hat per color name, so a hat tagged with three shades of
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
      // `hex`, not `color`: on the Search page `color` is also the Color
      // FILTER (palette names), and a hex landing there filtered every
      // ranked result away.
      href: `/search?hex=${encodeURIComponent(v.hex)}`,
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
            Couldn&rsquo;t load the collection, so no charts are shown — they would
            describe a collection you don&rsquo;t have.
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
  // The disposed list too: the Realized tile read "$0 · 0 sold" until it
  // arrived, which is a claim, not a placeholder.
  if (hatsQ.isLoading || casesQ.isLoading || disposedQ.isLoading) {
    return (
      <>
        <PageHead />
        <Panel title="The collection">
          <StatTilesSkeleton count={4} label="Loading stats…" />
        </Panel>
        <Panel title="Money">
          <StatTilesSkeleton count={4} label="Loading stats…" />
        </Panel>
      </>
    );
  }

  const conditionData: ChartDatum[] = ['new_with_tags', 'new', 'worn']
    .map(k => ({
      label: CONDITION_LABEL[k],
      value: hats.filter(h => h.condition === k).length,
      color: CONDITION_COLOR[k],
    }))
    .filter(d => d.value > 0);

  return (
    <>
      <PageHead />

      <nav className="hr-cp-jump" aria-label="Stats sections">
        {SECTIONS.map(s => (
          <a key={s.id} href={`#${s.id}-title`} className="hr-cp-chip" onClick={e => jumpTo(e, s.id)}>
            {s.label}
          </a>
        ))}
      </nav>

      {/* Two-up from the desktop breakpoint; a card whose content is wide
          (a row of tiles, a timeline) spans both columns via `hr-cp-span`.
          Every card here is an h3 under its section's h2. */}

      {/* ===== Totals ===== */}
      <Section id="stats-overview" title="Overview">
        <ChartCard title="The collection" as="h3" className="hr-cp-span">
          <StatTiles tiles={[
            { label: 'Hats', value: String(hats.length), tone: 'pink' },
            { label: 'Cases', value: String(cases.length), tone: 'cyan' },
            // A dash while rooms are unknown, never a zero — the page does not
            // wait on them, and "0 rooms" is a claim.
            { label: 'Rooms', value: roomsQ.data ? String(roomsQ.data.length) : '–', tone: 'purple' },
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
          as="h3"
          className="hr-cp-span"
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
          as="h3"
          className="hr-cp-span"
          subtitle="Each hat is valued from the best signal it has. Weaker bases are worth knowing about."
        >
          <BarList data={basisRows} colorize />
        </ChartCard>
      </Section>

      {/* ===== Composition ===== */}
      <Section id="stats-composition" title="Composition">
        <ChartCard title="By condition" as="h3">
          <Donut
            data={conditionData}
            centerValue={String(hats.length)}
            centerLabel="hats"
          />
        </ChartCard>

        <ChartCard title="By style" as="h3">
          <BarList
            data={countBy(hats, h => prettify(h.style)).map(d => ({
              ...d,
              href: `/hats?style=${encodeURIComponent(d.label.replace(/ /g, '_'))}`,
            }))}
            colorize
          />
        </ChartCard>

        <ChartCard title="By size" as="h3">
          <BarList data={countBy(hats, h => prettify(h.size))} colorize />
        </ChartCard>

        <ChartCard title="By brand" as="h3" subtitle="Hats with no brand identified are left out.">
          <BarList data={countBy(hats, h => h.brand, 12)} colorize />
        </ChartCard>

        <ChartCard title="By construction" as="h3" subtitle="Hats with no construction recorded are left out.">
          <BarList data={countBy(hats, h => h.construction, 12)} colorize />
        </ChartCard>

        <ChartCard title="Top colorways" as="h3">
          <BarList data={countBy(hats, h => h.colorway, 12)} colorize />
        </ChartCard>

        <ChartCard title="Artist & collab series" as="h3">
          <BarList
            data={countBy(hats, h => h.artist_series, 12)}
            emptyText="No collab or artist series recorded yet."
            colorize
          />
        </ChartCard>

        <ChartCard title="Colors" as="h3" subtitle="One vote per hat per color. Tap to search that shade.">
          <BarList data={colors} emptyText="No colors detected yet." />
        </ChartCard>
      </Section>

      {/* ===== Where it all lives ===== */}
      <Section id="stats-where" title="Where it lives">
        <ChartCard title="Hats by room" as="h3">
          <BarList data={countBy(hats, h => h.room_name)} colorize />
        </ChartCard>

        <ChartCard title="Value by room" as="h3">
          <BarList data={valueBy(hats, h => h.room_name)} colorize />
        </ChartCard>

        <ChartCard title="Fullest cases" as="h3" className="hr-cp-span" subtitle="Full in pink, overfull in orange.">
          <BarList data={caseFill} emptyText="No cases yet." />
        </ChartCard>
      </Section>

      {/* ===== Over time ===== */}
      <Section id="stats-time" title="Over time">
        <ChartCard
          title="Hats acquired"
          as="h3"
          className="hr-cp-span"
          subtitle="By purchase date where known, otherwise when the photo was added."
        >
          <TimeSeries points={timelines.acquired} />
        </ChartCard>

        <ChartCard
          title="Spend over time"
          as="h3"
          className="hr-cp-span"
          subtitle={
            valuation.costUnknown > 0
              ? <>Only the {valuation.spentCount} hats with a recorded price and date. The cyan line is the running total.</>
              : <>The cyan line is the running total.</>
          }
        >
          <TimeSeries points={timelines.spend} cumulative />
        </ChartCard>
      </Section>

      {/* ===== Leaderboards ===== */}
      <Section id="stats-leaders" title="Leaderboards">
        <ChartCard title="Most valuable" as="h3">
          <RankedHatList
            hats={[...hats]
              .filter(h => valueHat(h).value != null)
              .sort((a, b) => (valueHat(b).value ?? 0) - (valueHat(a).value ?? 0))
              .slice(0, 10)}
            valueFor={h => money(valueHat(h).value ?? 0)}
            empty="No hats have a value estimate yet."
          />
        </ChartCard>

        <ChartCard title="Most expensive (paid)" as="h3">
          <RankedHatList
            hats={[...hats]
              .filter(h => costOf(h) != null)
              .sort((a, b) => (costOf(b) ?? 0) - (costOf(a) ?? 0))
              .slice(0, 10)}
            valueFor={h => money(costOf(h) ?? 0)}
            empty="No purchase prices recorded yet."
          />
        </ChartCard>

        <ChartCard title="Most worn" as="h3">
          <RankedHatList
            hats={wear.mostWorn}
            valueFor={h => `${h.wear_count}×`}
            empty="No wears logged yet — tap “Wearing this today” on a hat."
          />
        </ChartCard>

        <ChartCard
          title="Best cost per wear"
          as="h3"
          subtitle="What you paid, divided by how often you've worn it. Needs both numbers."
        >
          <RankedHatList
            hats={wear.costPerWear.slice(0, 10).map(x => x.h)}
            valueFor={h => {
              const cost = costOf(h) ?? 0;
              return `${moneyPrecise(cost / (h.wear_count || 1))}/wear`;
            }}
            empty="Needs a purchase price and at least one logged wear."
          />
        </ChartCard>
      </Section>
    </>
  );
}
