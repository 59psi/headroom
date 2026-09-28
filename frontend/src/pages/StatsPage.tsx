/**
 * The whole collection as numbers.
 *
 * Everything here is derived client-side from the hat list the rest of the app
 * already loads, so opening this page costs one cached query rather than a new
 * reporting endpoint. That also means every figure is computed by the same
 * `lib/valuation` rule the home page and the valuation page use — the three
 * hand-rolled copies that preceded it had already drifted apart — and the
 * roll-ups over it are the ones the Valuation page shows (`lib/collectionViews`).
 */
import { useMemo, type MouseEvent, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { listRooms } from '../api/rooms';
import {
  BarList, Donut, StatTiles, StatTilesSkeleton, TimeSeries,
  type ChartDatum, type TimePoint,
} from '../components/charts/Charts';
import { caseRoomName } from '../components/cases/CaseTile';
import { LoadError } from '../components/common/LoadError';
import { PageHeader } from '../components/ui/PageHeader';
import { Panel } from '../components/ui/Panel';
import {
  money, moneyPrecise, realizedTotals, valueCases, valueCollection, valueHat, costOf,
} from '../lib/valuation';
import { basisRows, bucketize, topValued } from '../lib/collectionViews';
import { plural } from '../lib/format';
import { useCollection } from '../lib/useCollection';
import { useHatLabels } from '../lib/labels';
import { qk } from '../lib/queryKeys';
import { RankedHatList } from '../components/hats/RankedHatList';
import type { CaseRead, HatRead } from '../types';

const CONDITIONS = ['new_with_tags', 'new', 'worn'] as const;

const CONDITION_COLOR: Record<string, string> = {
  new_with_tags: 'var(--neon-cyan)',
  new: 'var(--neon-purple)',
  worn: 'var(--neon-orange)',
};

/**
 * Count hats by a key, drop the ones with no value for it, biggest first.
 *
 * The KEY and the LABEL are kept apart. The style bars used to label each row
 * with the stored value, underscores swapped for spaces ("a game"), and then
 * rebuilt the link's `?style=` by swapping them back — a link that worked only
 * because the label was lossy in exactly the reversible way. With the real
 * label ("A-Game") that round trip breaks, so `hrefFn` is handed the key.
 */
function countBy(
  hats: HatRead[],
  keyFn: (h: HatRead) => string | null | undefined,
  { label = k => k, href, limit }: {
    label?: (key: string) => string;
    href?: (key: string) => string;
    limit?: number;
  } = {},
): ChartDatum[] {
  const counts = new Map<string, number>();
  for (const h of hats) {
    const k = keyFn(h);
    if (!k) continue;
    counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  const rows = Array.from(counts, ([key, value]) => ({
    label: label(key),
    value,
    ...(href ? { href: href(key) } : {}),
  })).sort((a, b) => b.value - a.value || a.label.localeCompare(b.label));
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
    <PageHeader
      title="Stats"
      actions={
        <>
          <Link to="/valuation" className="btn btn-outline-secondary btn-sm">Valuation →</Link>
          <Link to="/" className="btn btn-outline-secondary btn-sm">← Home</Link>
        </>
      }
    />
  );
}

export function StatsPage() {
  const collection = useCollection();
  const { hats, disposed, cases } = collection;
  const roomsQ = useQuery({ queryKey: qk.rooms(), queryFn: listRooms });
  const labels = useHatLabels();

  const valuation = useMemo(() => valueCollection(hats), [hats]);
  // Cases are part of the collection: dozens of them at $49 each. Shown as
  // their own tile rather than folded into the hat figures — they are valued
  // at replacement cost, where hats are valued at market.
  const caseValue = useMemo(() => valueCases(cases), [cases]);
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
        label: `${c.display_id} · ${caseRoomName(c)}`,
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

  const bases = useMemo(() => basisRows(valuation), [valuation]);

  // A failed fetch must not render as an empty collection — see
  // `useCollection`. Errors are shown, not averaged in.
  if (collection.failed) {
    return (
      <>
        <PageHead />
        <LoadError
          what="Couldn’t load the collection, so no charts are shown — they would describe a collection you don’t have."
          queries={collection.queries}
        />
      </>
    );
  }
  // The disposed list too: the Realized tile read "$0 · 0 sold" until it
  // arrived, which is a claim, not a placeholder.
  if (collection.loading) {
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

  const conditionData: ChartDatum[] = CONDITIONS
    .map(k => ({
      label: labels.condition(k),
      value: hats.filter(h => h.condition === k).length,
      color: CONDITION_COLOR[k],
    }))
    .filter(d => d.value > 0);

  const valueByRoom: ChartDatum[] = bucketize(hats, h => h.room_name)
    .filter(b => b.valuedCount > 0)
    .map(b => ({ label: b.label, value: b.value, display: `${money(b.value)} · ${b.valuedCount}` }));

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
        <Panel title="The collection" as="h3" className="hr-cp-span">
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
        </Panel>

        <Panel
          title="Money"
          as="h3"
          className="hr-cp-span"
          description={<>Sale value is estimated — <Link to="/valuation">how it's worked out</Link>.</>}
        >
          <StatTiles tiles={[
            {
              label: 'Paid',
              value: money(valuation.spentTotal),
              tone: 'purple',
              sub: `${valuation.spentCount} of ${plural(valuation.total, 'hat')} priced`,
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
        </Panel>

        {/* ===== Where the value estimate comes from ===== */}
        <Panel
          title="What the estimate rests on"
          as="h3"
          className="hr-cp-span"
          description="Each hat is valued from the best signal it has. Weaker bases are worth knowing about."
        >
          <BarList data={bases} colorize />
        </Panel>
      </Section>

      {/* ===== Composition ===== */}
      <Section id="stats-composition" title="Composition">
        <Panel title="By condition" as="h3">
          <Donut
            data={conditionData}
            centerValue={String(hats.length)}
            centerLabel="hats"
          />
        </Panel>

        {/* Labeled as the rest of the app labels a style ("A-Game"), linked
            by the stored value the Hats filter reads. */}
        <Panel title="By style" as="h3">
          <BarList
            data={countBy(hats, h => h.style, {
              label: labels.style,
              href: key => `/hats?style=${encodeURIComponent(key)}`,
            })}
            colorize
          />
        </Panel>

        <Panel title="By size" as="h3">
          <BarList data={countBy(hats, h => h.size, { label: labels.size })} colorize />
        </Panel>

        <Panel title="By brand" as="h3" description="Hats with no brand identified are left out.">
          <BarList data={countBy(hats, h => h.brand, { limit: 12 })} colorize />
        </Panel>

        <Panel title="By construction" as="h3" description="Hats with no construction recorded are left out.">
          <BarList data={countBy(hats, h => h.construction, { limit: 12 })} colorize />
        </Panel>

        <Panel title="Top colorways" as="h3">
          <BarList data={countBy(hats, h => h.colorway, { limit: 12 })} colorize />
        </Panel>

        <Panel title="Artist & collab series" as="h3">
          <BarList
            data={countBy(hats, h => h.artist_series, { limit: 12 })}
            emptyText="No collab or artist series recorded yet."
            colorize
          />
        </Panel>

        <Panel title="Colors" as="h3" description="One vote per hat per color. Tap to search that shade.">
          <BarList data={colors} emptyText="No colors detected yet." />
        </Panel>
      </Section>

      {/* ===== Where it all lives ===== */}
      <Section id="stats-where" title="Where it lives">
        <Panel title="Hats by room" as="h3">
          <BarList data={countBy(hats, h => h.room_name)} colorize />
        </Panel>

        <Panel title="Value by room" as="h3">
          <BarList data={valueByRoom} colorize />
        </Panel>

        <Panel title="Fullest cases" as="h3" className="hr-cp-span" description="Full in pink, overfull in orange.">
          <BarList data={caseFill} emptyText="No cases yet." />
        </Panel>
      </Section>

      {/* ===== Over time ===== */}
      <Section id="stats-time" title="Over time">
        <Panel
          title="Hats acquired"
          as="h3"
          className="hr-cp-span"
          description="By purchase date where known, otherwise when the photo was added."
        >
          <TimeSeries points={timelines.acquired} />
        </Panel>

        <Panel
          title="Spend over time"
          as="h3"
          className="hr-cp-span"
          description={
            valuation.costUnknown > 0
              ? <>Only the {plural(valuation.spentCount, 'hat')} with a recorded price and date. The cyan line is the running total.</>
              : <>The cyan line is the running total.</>
          }
        >
          <TimeSeries points={timelines.spend} cumulative />
        </Panel>
      </Section>

      {/* ===== Leaderboards ===== */}
      <Section id="stats-leaders" title="Leaderboards">
        <Panel title="Most valuable" as="h3">
          <RankedHatList
            hats={topValued(hats)}
            valueFor={h => money(valueHat(h).value ?? 0)}
            empty="No hats have a value estimate yet."
          />
        </Panel>

        <Panel title="Most expensive (paid)" as="h3">
          <RankedHatList
            hats={[...hats]
              .filter(h => costOf(h) != null)
              .sort((a, b) => (costOf(b) ?? 0) - (costOf(a) ?? 0))
              .slice(0, 10)}
            valueFor={h => money(costOf(h) ?? 0)}
            empty="No purchase prices recorded yet."
          />
        </Panel>

        <Panel title="Most worn" as="h3">
          <RankedHatList
            hats={wear.mostWorn}
            valueFor={h => `${h.wear_count}×`}
            empty="No wears logged yet — tap “Wearing this today” on a hat."
          />
        </Panel>

        <Panel
          title="Best cost per wear"
          as="h3"
          description="What you paid, divided by how often you've worn it. Needs both numbers."
        >
          <RankedHatList
            hats={wear.costPerWear.slice(0, 10).map(x => x.h)}
            valueFor={h => {
              const cost = costOf(h) ?? 0;
              return `${moneyPrecise(cost / (h.wear_count || 1))}/wear`;
            }}
            empty="Needs a purchase price and at least one logged wear."
          />
        </Panel>
      </Section>
    </>
  );
}
