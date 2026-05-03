import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { listCases } from '../api/cases';
import { listHats } from '../api/hats';
import { listRooms } from '../api/rooms';
import { getLogo } from '../api/settings';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

function shuffleArray<T>(arr: T[]): T[] {
  const shuffled = [...arr];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled;
}

export function HomePage() {
  const cases = useQuery({ queryKey: ['cases'], queryFn: listCases });
  const hats = useQuery({ queryKey: ['hats'], queryFn: () => listHats() });
  const rooms = useQuery({ queryKey: ['rooms'], queryFn: listRooms });
  const logo = useQuery({ queryKey: ['settings', 'logo'], queryFn: getLogo });
  const navigate = useNavigate();
  const [activeIndex, setActiveIndex] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const touchStartX = useRef<number | null>(null);

  const hatsWithPhotos = useMemo(
    () => shuffleArray(hats.data?.filter(h => h.photo_path) ?? []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [hats.dataUpdatedAt]
  );

  const goNext = useCallback(() => {
    if (hatsWithPhotos.length <= 1) return;
    setActiveIndex(prev => (prev + 1) % hatsWithPhotos.length);
  }, [hatsWithPhotos.length]);

  const goPrev = useCallback(() => {
    if (hatsWithPhotos.length <= 1) return;
    setActiveIndex(prev => (prev - 1 + hatsWithPhotos.length) % hatsWithPhotos.length);
  }, [hatsWithPhotos.length]);

  useEffect(() => {
    if (hatsWithPhotos.length <= 1) return;
    intervalRef.current = setInterval(goNext, 5000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [hatsWithPhotos.length, goNext]);

  const resetTimer = useCallback(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    if (hatsWithPhotos.length > 1) {
      intervalRef.current = setInterval(goNext, 5000);
    }
  }, [hatsWithPhotos.length, goNext]);

  function handleTouchStart(e: React.TouchEvent) {
    touchStartX.current = e.touches[0].clientX;
  }

  function handleTouchEnd(e: React.TouchEvent) {
    if (touchStartX.current === null) return;
    const dx = e.changedTouches[0].clientX - touchStartX.current;
    if (Math.abs(dx) > 40) {
      if (dx < 0) goNext(); else goPrev();
      resetTimer();
    }
    touchStartX.current = null;
  }

  // ALL hooks must run on every render in the same order — Rules of Hooks.
  // The valuation useMemo MUST live above the early-return below.
  const valuation = useMemo(() => {
    // Resale heuristic — applied only when the hat doesn't have a user-set
    // resale_price. Rough industry rules of thumb for branded headwear.
    const RESALE_MULTIPLIER: Record<string, number> = {
      new_with_tags: 0.65,
      new: 0.45,
      worn: 0.30,
    };
    const buckets: Record<string, { count: number; newTotal: number; resaleTotal: number; label: string }> = {
      new_with_tags: { count: 0, newTotal: 0, resaleTotal: 0, label: 'New w/ Tags' },
      new: { count: 0, newTotal: 0, resaleTotal: 0, label: 'New' },
      worn: { count: 0, newTotal: 0, resaleTotal: 0, label: 'Worn' },
    };
    let appraisedHatCount = 0;
    (hats.data ?? []).forEach(h => {
      const bucket = buckets[h.condition];
      if (!bucket) return;
      bucket.count += 1;
      const newPrice = h.estimated_new_price ?? 0;
      if (newPrice > 0) appraisedHatCount += 1;
      const resaleMult = RESALE_MULTIPLIER[h.condition] ?? 0.4;
      const resalePrice = h.resale_price ?? newPrice * resaleMult;
      bucket.newTotal += newPrice;
      bucket.resaleTotal += resalePrice;
    });
    const totalNew = Object.values(buckets).reduce((s, b) => s + b.newTotal, 0);
    const totalResale = Object.values(buckets).reduce((s, b) => s + b.resaleTotal, 0);
    return { buckets, totalNew, totalResale, appraisedHatCount };
  }, [hats.data]);

  if (cases.isLoading || hats.isLoading) return <LoadingSpinner />;

  const totalHats = hats.data?.length ?? 0;
  const totalCases = cases.data?.length ?? 0;
  const totalRooms = rooms.data?.length ?? 0;
  const archiveCases = cases.data?.filter(c => c.case_type === 'archive').length ?? 0;
  const dailyCases = cases.data?.filter(c => c.case_type === 'daily_wear').length ?? 0;

  return (
    <>
      <div className="hr-hero mb-3">
        {logo.data?.logo_path && (
          <img src={`/uploads/${logo.data.logo_path}`} alt="" className="hr-logo" />
        )}
        <h1>Headroom</h1>
        <p>The Outrun-grade vault for your hat collection.</p>
      </div>

      <div className="hr-stat-grid mb-3">
        <div className="hr-stat" style={{ '--accent': 'var(--gradient-pink-cyan)' } as React.CSSProperties}>
          <div className="hr-stat-value">{totalHats}</div>
          <div className="hr-stat-label">Hats</div>
        </div>
        <div className="hr-stat" style={{ '--accent': 'var(--gradient-cyan-purple)' } as React.CSSProperties}>
          <div className="hr-stat-value">{totalCases}</div>
          <div className="hr-stat-label">Cases</div>
        </div>
        <div className="hr-stat">
          <div className="hr-stat-value">{archiveCases}</div>
          <div className="hr-stat-label">Archive</div>
        </div>
        <div className="hr-stat">
          <div className="hr-stat-value">{dailyCases}</div>
          <div className="hr-stat-label">Daily</div>
        </div>
        <div className="hr-stat">
          <div className="hr-stat-value">{totalRooms}</div>
          <div className="hr-stat-label">Rooms</div>
        </div>
      </div>

      {valuation.totalNew > 0 && (
        <div className="card hr-feature mb-3">
          <div className="card-body">
            <div className="d-flex justify-content-between align-items-start gap-2 flex-wrap mb-3">
              <div>
                <div className="card-title mb-1">Valuation Overview</div>
                <div className="text-secondary small">
                  Across {valuation.appraisedHatCount} appraised hat{valuation.appraisedHatCount === 1 ? '' : 's'}.
                  Resale = manual override, else condition-based estimate (NWT 65% · New 45% · Worn 30%).
                </div>
              </div>
            </div>

            <div className="row g-2 mb-3">
              <div className="col-6">
                <div className="hr-metric">
                  <div className="hr-metric-label">Original (new)</div>
                  <div className="hr-metric-value hr-price hr-price-large">
                    ${valuation.totalNew.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </div>
                </div>
              </div>
              <div className="col-6">
                <div className="hr-metric">
                  <div className="hr-metric-label">Est. resale</div>
                  <div className="hr-metric-value hr-price hr-price-large">
                    ${valuation.totalResale.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </div>
                  <div className="text-muted" style={{ fontSize: '0.7rem', marginTop: 2 }}>
                    {valuation.totalNew > 0
                      ? `${Math.round((valuation.totalResale / valuation.totalNew) * 100)}% of new`
                      : ''}
                  </div>
                </div>
              </div>
            </div>

            <div className="d-flex justify-content-between align-items-center mb-2">
              <div className="hr-tier-label">By condition</div>
              <Link to="/valuation" className="btn btn-outline-primary btn-sm">
                Full breakdown →
              </Link>
            </div>
            {(['new_with_tags', 'new', 'worn'] as const).map(key => {
              const b = valuation.buckets[key];
              if (b.count === 0) return null;
              return (
                <div key={key} className="hr-color-row" style={{ paddingTop: '0.5rem' }}>
                  <div className="flex-grow-1">
                    <div className="fw-semibold">{b.label}</div>
                    <div className="text-muted small font-mono">
                      {b.count} hat{b.count === 1 ? '' : 's'}
                    </div>
                  </div>
                  <div className="text-end">
                    <div className="font-mono small">
                      <span className="text-secondary">new </span>
                      <span style={{ color: 'var(--neon-cyan)' }}>
                        ${b.newTotal.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                      </span>
                    </div>
                    <div className="font-mono small">
                      <span className="text-secondary">resale </span>
                      <span style={{ color: 'var(--neon-pink)' }}>
                        ${b.resaleTotal.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {hatsWithPhotos.length > 0 && (
        <div
          className="hr-carousel mb-3"
          onTouchStart={handleTouchStart}
          onTouchEnd={handleTouchEnd}
        >
          <div
            onClick={() => navigate(`/hats/${hatsWithPhotos[activeIndex].id}`)}
            style={{ cursor: 'pointer' }}
          >
            <img
              src={`/uploads/${hatsWithPhotos[activeIndex].photo_path}`}
              alt={hatsWithPhotos[activeIndex].display_id || `Hat #${hatsWithPhotos[activeIndex].id}`}
            />
            <div className="carousel-caption">
              <h6>{hatsWithPhotos[activeIndex].display_id || `Hat #${hatsWithPhotos[activeIndex].id}`}</h6>
              <small>{hatsWithPhotos[activeIndex].style.replace(/_/g, ' ')}</small>
            </div>
          </div>
          {hatsWithPhotos.length > 1 && (
            <>
              <button
                className="carousel-control-prev"
                type="button"
                onClick={(e) => { e.stopPropagation(); goPrev(); resetTimer(); }}
                aria-label="Previous"
              >
                <span className="carousel-control-prev-icon" />
              </button>
              <button
                className="carousel-control-next"
                type="button"
                onClick={(e) => { e.stopPropagation(); goNext(); resetTimer(); }}
                aria-label="Next"
              >
                <span className="carousel-control-next-icon" />
              </button>
            </>
          )}
        </div>
      )}

      <div className="d-flex gap-2">
        <Link to="/hats/new" className="btn btn-primary flex-fill">+ Add Hat</Link>
        <Link to="/cases/new" className="btn btn-outline-primary flex-fill">+ Add Case</Link>
      </div>
    </>
  );
}
