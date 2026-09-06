/**
 * The chart set for the stats page.
 *
 * Hand-rolled rather than pulled from a charting library, for the same reason
 * this app has no UI framework: the whole visual identity is a small set of
 * tokens, and every charting library arrives with its own opinions about
 * color, type and spacing that then have to be fought. These are a few dozen
 * lines each and read the tokens directly.
 *
 * Mobile-first throughout. `BarList` is HTML rather than SVG specifically so
 * that long labels ("Ocean Camo Hydro") wrap and truncate the way text is
 * supposed to — inside SVG they'd need manual measurement to avoid running off
 * the edge of a phone.
 */
import type { ReactNode } from 'react';
import { Link } from 'react-router';

/** Series colors, in assignment order. Distinguishable on a dark canvas. */
export const SERIES_COLORS = [
  'var(--neon-pink)',
  'var(--neon-cyan)',
  'var(--neon-purple)',
  'var(--neon-orange)',
  'var(--neon-yellow)',
  'var(--neon-green)',
  'var(--neon-sky)',
  'var(--neon-rose)',
];

export function seriesColor(i: number): string {
  return SERIES_COLORS[i % SERIES_COLORS.length];
}

export interface ChartDatum {
  label: string;
  value: number;
  /** Right-hand annotation — a formatted total, a count, whatever the chart is about. */
  display?: string;
  color?: string;
  href?: string;
}

/* ===== Bar list ================================================== */

/**
 * Ranked horizontal bars.
 *
 * The workhorse: it survives 30 categories and 40-character labels on a
 * 375px screen, which a vertical bar chart does not.
 */
export function BarList({
  data,
  max,
  emptyText = 'Nothing to chart yet.',
  colorize = false,
}: {
  data: ChartDatum[];
  /** Scale ceiling. Defaults to the largest value present. */
  max?: number;
  emptyText?: string;
  /** Give each row its own series color instead of one accent for all. */
  colorize?: boolean;
}) {
  if (!data.length) {
    return <p className="text-muted small mb-0">{emptyText}</p>;
  }
  // Guard the divisor: an all-zero series (a brand-new collection with no
  // wears recorded) would otherwise make every width NaN and render nothing
  // at all, which looks like a broken page rather than an empty one.
  const ceiling = Math.max(max ?? 0, ...data.map(d => d.value), 1);

  return (
    <div className="hr-barlist">
      {data.map((d, i) => {
        const width = `${Math.max((d.value / ceiling) * 100, d.value > 0 ? 1.5 : 0)}%`;
        const color = d.color ?? (colorize ? seriesColor(i) : 'var(--neon-pink)');
        const row = (
          <>
            <div className="hr-barlist-head">
              <span className="hr-barlist-label" title={d.label}>{d.label}</span>
              <span className="hr-barlist-value">{d.display ?? d.value.toLocaleString()}</span>
            </div>
            <div className="hr-barlist-track">
              <div
                className="hr-barlist-fill"
                style={{ width, background: color }}
              />
            </div>
          </>
        );
        // Every href a chart is fed is an in-app path (a search, a case, a
        // filtered list); a plain <a> reloaded the whole SPA to follow it.
        return d.href ? (
          <Link key={d.label} to={d.href} className="hr-barlist-row hr-barlist-row-link">{row}</Link>
        ) : (
          <div key={d.label} className="hr-barlist-row">{row}</div>
        );
      })}
    </div>
  );
}

/* ===== Donut ===================================================== */

/**
 * Proportional ring with a legend and a total in the middle.
 *
 * Deliberately capped at a handful of slices by the caller — a donut with
 * twenty segments is a decorative circle, and `BarList` is the honest choice
 * for those.
 */
export function Donut({
  data,
  centerLabel,
  centerValue,
}: {
  data: ChartDatum[];
  centerLabel?: string;
  centerValue?: string;
}) {
  const total = data.reduce((s, d) => s + d.value, 0);
  if (total <= 0) {
    return <p className="text-muted small mb-0">Nothing to chart yet.</p>;
  }

  const size = 168;
  const stroke = 26;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  return (
    <div className="hr-donut-wrap">
      <svg
        viewBox={`0 0 ${size} ${size}`}
        className="hr-donut"
        role="img"
        aria-label={data.map(d => `${d.label}: ${d.value}`).join(', ')}
      >
        <circle
          cx={size / 2} cy={size / 2} r={radius}
          fill="none" stroke="var(--bg-input)" strokeWidth={stroke}
        />
        {data.map((d, i) => {
          const fraction = d.value / total;
          const dash = fraction * circumference;
          const seg = (
            <circle
              key={d.label}
              cx={size / 2} cy={size / 2} r={radius}
              fill="none"
              stroke={d.color ?? seriesColor(i)}
              strokeWidth={stroke}
              strokeDasharray={`${dash} ${circumference - dash}`}
              strokeDashoffset={-offset}
              // Rotate so the first slice starts at 12 o'clock rather than
              // 3 o'clock, which is where SVG angles begin.
              transform={`rotate(-90 ${size / 2} ${size / 2})`}
            />
          );
          offset += dash;
          return seg;
        })}
        {centerValue && (
          <text
            x="50%" y="47%"
            textAnchor="middle" dominantBaseline="middle"
            className="hr-donut-center-value"
          >{centerValue}</text>
        )}
        {centerLabel && (
          <text
            x="50%" y="61%"
            textAnchor="middle" dominantBaseline="middle"
            className="hr-donut-center-label"
          >{centerLabel}</text>
        )}
      </svg>
      <ul className="hr-donut-legend">
        {data.map((d, i) => (
          <li key={d.label}>
            <span className="hr-legend-dot" style={{ background: d.color ?? seriesColor(i) }} />
            <span className="hr-legend-label">{d.label}</span>
            <span className="hr-legend-value">
              {d.display ?? d.value.toLocaleString()}
              <span className="hr-legend-pct">{Math.round((d.value / total) * 100)}%</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ===== Time series =============================================== */

export interface TimePoint {
  /** Bucket key, e.g. "2026-03". Sorts lexically, which is why it's this shape. */
  key: string;
  label: string;
  value: number;
  display?: string;
}

/**
 * Columns over time, with an optional cumulative line laid over them.
 *
 * Renders every bucket including the empty ones — a gap in acquisitions is
 * information, and a chart that silently closes the gaps turns a six-month
 * pause into a continuous run.
 */
export function TimeSeries({
  points,
  cumulative = false,
  height = 150,
  barColor = 'var(--neon-pink)',
  lineColor = 'var(--neon-cyan)',
}: {
  points: TimePoint[];
  cumulative?: boolean;
  height?: number;
  barColor?: string;
  lineColor?: string;
}) {
  if (!points.length) {
    return <p className="text-muted small mb-0">Nothing to chart yet.</p>;
  }

  const width = Math.max(points.length * 26, 260);
  const pad = { top: 12, bottom: 26, left: 0, right: 0 };
  const plotH = height - pad.top - pad.bottom;
  const barMax = Math.max(...points.map(p => p.value), 1);
  const slot = width / points.length;
  const barW = Math.min(slot * 0.6, 22);

  let running = 0;
  const runningTotals = points.map(p => (running += p.value));
  const cumMax = Math.max(running, 1);

  const linePath = points
    .map((_, i) => {
      const x = i * slot + slot / 2;
      const y = pad.top + plotH - (runningTotals[i] / cumMax) * plotH;
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  // Thin the axis labels rather than letting them collide — on a phone a
  // 30-month series has room for about six.
  const labelEvery = Math.ceil(points.length / 6);

  return (
    <div className="hr-timeseries-scroll">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        style={{ width: '100%', minWidth: width > 320 ? width : undefined, height }}
        role="img"
        aria-label={points.map(p => `${p.label}: ${p.display ?? p.value}`).join(', ')}
        preserveAspectRatio="none"
      >
        {points.map((p, i) => {
          const h = (p.value / barMax) * plotH;
          const x = i * slot + (slot - barW) / 2;
          return (
            <rect
              key={p.key}
              x={x}
              y={pad.top + plotH - h}
              width={barW}
              height={Math.max(h, p.value > 0 ? 2 : 0)}
              rx={3}
              fill={barColor}
              opacity={0.85}
            >
              <title>{`${p.label}: ${p.display ?? p.value}`}</title>
            </rect>
          );
        })}
        {cumulative && (
          <path d={linePath} fill="none" stroke={lineColor} strokeWidth={2} vectorEffect="non-scaling-stroke" />
        )}
        {points.map((p, i) => (
          i % labelEvery === 0 ? (
            <text
              key={`${p.key}-label`}
              x={i * slot + slot / 2}
              y={height - 8}
              textAnchor="middle"
              className="hr-chart-axis"
            >{p.label}</text>
          ) : null
        ))}
      </svg>
    </div>
  );
}

/* ===== Layout helpers ============================================ */

/** A titled block on the stats page. Keeps section chrome in one place. */
export function ChartCard({
  title,
  subtitle,
  action,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="d-flex justify-content-between align-items-start gap-2 mb-2">
          <div style={{ minWidth: 0 }}>
            <div className="card-title mb-0">{title}</div>
            {subtitle && <div className="text-muted small mt-1">{subtitle}</div>}
          </div>
          {action}
        </div>
        {children}
      </div>
    </div>
  );
}

/** Big-number tiles. `tone` picks the accent; `sub` is the caveat line. */
export function StatTiles({
  tiles,
}: {
  tiles: Array<{ label: string; value: string; sub?: ReactNode; tone?: 'pink' | 'cyan' | 'purple' | 'muted' }>;
}) {
  return (
    <div className="hr-tile-grid">
      {tiles.map(t => (
        <div key={t.label} className={`hr-tile hr-tile-${t.tone ?? 'cyan'}`}>
          <div className="hr-tile-label">{t.label}</div>
          <div className="hr-tile-value">{t.value}</div>
          {t.sub && <div className="hr-tile-sub">{t.sub}</div>}
        </div>
      ))}
    </div>
  );
}
