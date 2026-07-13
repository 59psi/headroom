import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { listHats } from '../api/hats';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import type { HatRead } from '../types';

const RESALE_MULTIPLIER: Record<string, number> = {
  new_with_tags: 0.65,
  new: 0.45,
  worn: 0.30,
};

function resaleFor(h: HatRead): number {
  const newPrice = h.estimated_new_price ?? 0;
  const fallback = newPrice * (RESALE_MULTIPLIER[h.condition] ?? 0.4);
  return h.resale_price ?? fallback;
}

function fmt$(n: number): string {
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

interface Bucket {
  key: string;
  label: string;
  count: number;
  newTotal: number;
  resaleTotal: number;
}

function bucketize(hats: HatRead[], keyFn: (h: HatRead) => string | null, labelFn: (k: string) => string = (k) => k): Bucket[] {
  const map = new Map<string, Bucket>();
  for (const h of hats) {
    const k = keyFn(h);
    if (!k) continue;
    const newPrice = h.estimated_new_price ?? 0;
    const resale = resaleFor(h);
    const existing = map.get(k);
    if (existing) {
      existing.count += 1;
      existing.newTotal += newPrice;
      existing.resaleTotal += resale;
    } else {
      map.set(k, { key: k, label: labelFn(k), count: 1, newTotal: newPrice, resaleTotal: resale });
    }
  }
  return Array.from(map.values()).sort((a, b) => b.newTotal - a.newTotal);
}

function BucketTable({ title, buckets }: { title: string; buckets: Bucket[] }) {
  if (buckets.length === 0) return null;
  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title mb-2">{title}</div>
        {buckets.map(b => (
          <div key={b.key} className="hr-color-row" style={{ paddingTop: '0.5rem' }}>
            <div className="flex-grow-1" style={{ minWidth: 0 }}>
              <div className="fw-semibold" style={{
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
              }}>{b.label}</div>
              <div className="text-muted small font-mono">{b.count} hat{b.count === 1 ? '' : 's'}</div>
            </div>
            <div className="text-end">
              <div className="font-mono small">
                <span className="text-secondary">new </span>
                <span style={{ color: 'var(--neon-cyan)' }}>{fmt$(b.newTotal)}</span>
              </div>
              <div className="font-mono small">
                <span className="text-secondary">resale </span>
                <span style={{ color: 'var(--neon-pink)' }}>{fmt$(b.resaleTotal)}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ValuationPage() {
  const hats = useQuery({ queryKey: ['hats'], queryFn: () => listHats() });

  const analysis = useMemo(() => {
    const data = hats.data ?? [];
    const appraised = data.filter(h => (h.estimated_new_price ?? 0) > 0);
    const totalNew = appraised.reduce((s, h) => s + (h.estimated_new_price ?? 0), 0);
    const totalResale = appraised.reduce((s, h) => s + resaleFor(h), 0);

    const conditionLabels: Record<string, string> = {
      new_with_tags: 'New with Tags',
      new: 'New',
      worn: 'Worn',
    };

    return {
      totalHats: data.length,
      appraisedCount: appraised.length,
      unappraisedCount: data.length - appraised.length,
      totalNew,
      totalResale,
      retentionPct: totalNew > 0 ? Math.round((totalResale / totalNew) * 100) : 0,
      byCondition: bucketize(data, h => h.condition, k => conditionLabels[k] ?? k),
      byBrand: bucketize(data, h => h.brand, k => k),
      byStyle: bucketize(data, h => h.style, k => k.replace(/_/g, ' ')),
      byRoom: bucketize(data, h => h.room_name, k => k),
      topByNew: [...appraised]
        .sort((a, b) => (b.estimated_new_price ?? 0) - (a.estimated_new_price ?? 0))
        .slice(0, 10),
      topByResale: [...appraised]
        .sort((a, b) => resaleFor(b) - resaleFor(a))
        .slice(0, 10),
      neglected: [...data]
        .filter(h => !h.disposed_at)
        .sort((a, b) => (a.date_last_worn ?? '0000') < (b.date_last_worn ?? '0000') ? -1 : 1)
        .slice(0, 5),
    };
  }, [hats.data]);

  if (hats.isLoading) return <LoadingSpinner />;

  if (analysis.appraisedCount === 0) {
    return (
      <>
        <h1 className="mb-3">Valuation</h1>
        <div className="card mb-3">
          <div className="card-body text-center py-5">
            <p className="text-secondary mb-2">
              No appraised hats yet ({analysis.totalHats} hat{analysis.totalHats === 1 ? '' : 's'} in collection).
            </p>
            <p className="text-muted small mb-3">
              Upload hat photos with a Claude API key configured — Claude estimates the
              new retail price during analysis. You can also enter prices manually on
              each hat's edit page.
            </p>
            <Link to="/settings" className="btn btn-outline-primary btn-sm">Configure API Key</Link>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3 gap-2 flex-wrap">
        <h1>Valuation</h1>
        <Link to="/" className="btn btn-outline-secondary btn-sm">← Home</Link>
      </div>

      <div className="card hr-feature mb-3">
        <div className="card-body">
          <div className="card-title">Collection Totals</div>
          <div className="row g-2 mb-2">
            <div className="col-6">
              <div className="hr-metric">
                <div className="hr-metric-label">Original (new)</div>
                <div className="hr-metric-value hr-price hr-price-large">{fmt$(analysis.totalNew)}</div>
              </div>
            </div>
            <div className="col-6">
              <div className="hr-metric">
                <div className="hr-metric-label">Est. resale</div>
                <div className="hr-metric-value hr-price hr-price-large">{fmt$(analysis.totalResale)}</div>
                <div className="text-muted" style={{ fontSize: '0.7rem', marginTop: 2 }}>
                  {analysis.retentionPct}% of new
                </div>
              </div>
            </div>
          </div>
          <p className="text-muted small mb-0" style={{ fontSize: '0.75rem' }}>
            Across {analysis.appraisedCount} appraised hat{analysis.appraisedCount === 1 ? '' : 's'}
            {analysis.unappraisedCount > 0 && ` · ${analysis.unappraisedCount} not yet appraised`}.
            Resale = manual override per hat, else estimate (NWT 65% · New 45% · Worn 30%).
          </p>
        </div>
      </div>

      <BucketTable title="By Condition" buckets={analysis.byCondition} />
      <BucketTable title="By Brand" buckets={analysis.byBrand} />
      <BucketTable title="By Style" buckets={analysis.byStyle} />
      <BucketTable title="By Room" buckets={analysis.byRoom} />

      <div className="card mb-3">
        <div className="card-body">
          <div className="card-title mb-2">Most Valuable (new)</div>
          {analysis.topByNew.map((h, i) => (
            <Link
              key={h.id}
              to={`/hats/${h.id}`}
              className="hr-color-row text-decoration-none"
              style={{ paddingTop: '0.5rem' }}
            >
              <div className="font-mono fw-bold" style={{ color: 'var(--neon-purple)', minWidth: 24 }}>
                {i + 1}.
              </div>
              {h.photo_path ? (
                <img src={`/uploads/${h.photo_path}`} alt="" className="hr-thumb flex-shrink-0" style={{ width: 40, height: 40 }} />
              ) : (
                <div className="rounded flex-shrink-0" style={{ width: 40, height: 40, background: 'rgba(0,0,0,0.3)' }} />
              )}
              <div className="flex-grow-1" style={{ minWidth: 0 }}>
                <div className="font-mono small" style={{ color: 'var(--neon-cyan)' }}>
                  {h.display_id || `Hat #${h.id}`}
                </div>
                <div className="text-secondary small" style={{
                  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                }}>
                  {h.brand || h.style.replace(/_/g, ' ')}
                  {h.model_name && ` · ${h.model_name}`}
                </div>
              </div>
              <div className="font-mono fw-bold" style={{ color: 'var(--neon-cyan)' }}>
                {fmt$(h.estimated_new_price ?? 0)}
              </div>
            </Link>
          ))}
        </div>
      </div>

      <div className="card mb-3">
        <div className="card-body">
          <div className="card-title mb-2">Most Valuable (resale)</div>
          {analysis.topByResale.map((h, i) => (
            <Link
              key={h.id}
              to={`/hats/${h.id}`}
              className="hr-color-row text-decoration-none"
              style={{ paddingTop: '0.5rem' }}
            >
              <div className="font-mono fw-bold" style={{ color: 'var(--neon-purple)', minWidth: 24 }}>
                {i + 1}.
              </div>
              {h.photo_path ? (
                <img src={`/uploads/${h.photo_path}`} alt="" className="hr-thumb flex-shrink-0" style={{ width: 40, height: 40 }} />
              ) : (
                <div className="rounded flex-shrink-0" style={{ width: 40, height: 40, background: 'rgba(0,0,0,0.3)' }} />
              )}
              <div className="flex-grow-1" style={{ minWidth: 0 }}>
                <div className="font-mono small" style={{ color: 'var(--neon-cyan)' }}>
                  {h.display_id || `Hat #${h.id}`}
                </div>
                <div className="text-secondary small" style={{
                  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                }}>
                  {h.brand || h.style.replace(/_/g, ' ')}
                  {h.model_name && ` · ${h.model_name}`}
                </div>
              </div>
              <div className="font-mono fw-bold" style={{ color: 'var(--neon-pink)' }}>
                {fmt$(resaleFor(h))}
              </div>
            </Link>
          ))}
        </div>
      </div>

      {/* === Wear rotation: most neglected active hats === */}
      <div className="card mb-3">
        <div className="card-body">
          <div className="card-title">Wear Rotation</div>
          <p className="text-secondary small mb-2">Longest since last worn — give these some sun:</p>
          {analysis.neglected.map(h => (
            <Link key={h.id} to={`/hats/${h.id}`} className="hr-color-row text-decoration-none" style={{ paddingTop: '0.5rem' }}>
              {h.photo_path ? (
                <img src={`/uploads/${h.photo_path}`} alt="" className="hr-thumb flex-shrink-0" style={{ width: 40, height: 40 }} />
              ) : (
                <div className="rounded flex-shrink-0" style={{ width: 40, height: 40, background: 'rgba(0,0,0,0.3)' }} />
              )}
              <div className="flex-grow-1" style={{ minWidth: 0 }}>
                <div className="font-mono small" style={{ color: 'var(--neon-cyan)' }}>{h.display_id || `Hat #${h.id}`}</div>
                <div className="text-secondary small">{h.brand || h.style.replace(/_/g, ' ')}{h.model_name && ` · ${h.model_name}`}</div>
              </div>
              <div className="text-secondary small font-mono">
                {h.date_last_worn ?? 'never worn'}
              </div>
            </Link>
          ))}
        </div>
      </div>
    </>
  );
}
