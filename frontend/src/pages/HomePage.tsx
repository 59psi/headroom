import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router';
import { listCases } from '../api/cases';
import { listAllHats } from '../api/hats';
import { listRooms } from '../api/rooms';
import { getLogo } from '../api/settings';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { StatTiles } from '../components/charts/Charts';
import { money, valueCases, valueCollection } from '../lib/valuation';
import { useMediaQuery } from '../lib/useMediaQuery';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

/** Desktop, as this app already defines it — the width where TopNav appears. */
const TWO_UP_QUERY = '(min-width: 992px)';

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
  const hats = useQuery({ queryKey: ['hats'], queryFn: listAllHats });
  const rooms = useQuery({ queryKey: ['rooms'], queryFn: listRooms });
  const logo = useQuery({ queryKey: ['settings', 'logo'], queryFn: getLogo });
  const navigate = useNavigate();
  const [activeIndex, setActiveIndex] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const touchStartX = useRef<number | null>(null);
  const twoUp = useMediaQuery(TWO_UP_QUERY);

  const withPhotos = useMemo(
    () => hats.data?.filter(h => h.photo_path) ?? [],
    [hats.data]
  );
  // Reshuffle only when the SET of hats changes, not on every refetch.
  // `dataUpdatedAt` ticks on each poll even when the payload is identical, so
  // keying on it reshuffled the deck and made the visible hat jump at random.
  const photoKey = withPhotos.map(h => h.id).join(',');
  const hatsWithPhotos = useMemo(
    () => shuffleArray(withPhotos),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [photoKey]
  );
  // Two hats on a desktop, one on a phone — but never more than exist, or a
  // single-photo collection renders the same hat twice side by side, which
  // reads as a bug rather than a layout.
  const visibleCount = Math.min(twoUp ? 2 : 1, Math.max(hatsWithPhotos.length, 1));

  // Take a window rather than indexing blindly: the list can shrink under a
  // running carousel (a hat disposed or deleted on another device, then a
  // refetch), and `hatsWithPhotos[activeIndex]` would then be undefined and
  // throw, taking the whole page down to the ErrorBoundary.
  // No second clamp here — `visibleCount` is already bounded by the number of
  // hats with photos, and clamping twice invites the two rules to drift.
  const visibleHats = useMemo(
    () =>
      hatsWithPhotos.length
        ? Array.from({ length: visibleCount }, (_, i) =>
            hatsWithPhotos[(activeIndex + i) % hatsWithPhotos.length]
          )
        : [],
    [hatsWithPhotos, activeIndex, visibleCount]
  );

  // Nothing to page to when every hat is already on screen. Generalises the
  // old `length <= 1` guard, which on a two-up view left the arrows visible
  // for a two-hat collection and stepping by 2 landed back where it started.
  const canPage = hatsWithPhotos.length > visibleCount;

  // Advance by a full screenful so both panes turn over together and the
  // arrows page rather than shuffle one hat along.
  const goNext = useCallback(() => {
    if (!canPage) return;
    setActiveIndex(prev => (prev + visibleCount) % hatsWithPhotos.length);
  }, [canPage, visibleCount, hatsWithPhotos.length]);

  const goPrev = useCallback(() => {
    if (!canPage) return;
    setActiveIndex(
      prev => (prev - visibleCount + hatsWithPhotos.length) % hatsWithPhotos.length
    );
  }, [canPage, visibleCount, hatsWithPhotos.length]);

  useEffect(() => {
    if (!canPage) return;
    intervalRef.current = setInterval(goNext, 5000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [canPage, goNext]);

  const resetTimer = useCallback(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    if (canPage) {
      intervalRef.current = setInterval(goNext, 5000);
    }
  }, [canPage, goNext]);

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
  const valuation = useMemo(() => valueCollection(hats.data ?? []), [hats.data]);
  // Cases count too — dozens at $49 each, previously absent from every total.
  const caseValue = useMemo(() => valueCases(cases.data ?? []), [cases.data]);

  // A failed fetch must not render as an empty collection. `?? []` turns a
  // 500 or a dropped connection into "$0 across 0 hats", which is a confident
  // wrong answer — the exact thing `valueHat` returns `null` rather than 0 to
  // avoid. Errors are shown, not averaged in.
  if (cases.isError || hats.isError) {
    return (
      <div className="alert alert-danger" role="alert">
        Couldn&rsquo;t load your collection. Reload to try again.
      </div>
    );
  }
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

      {/* Every count here is a question with an answer elsewhere in the app
          ("35 cases" → show me them), so every count is the link to it.
          Archive and Daily deep-link into the Cases page's own type filter
          rather than duplicating a filtered list. */}
      <nav className="hr-stat-rail mb-3" aria-label="Collection summary">
        <div className="hr-stat-row">
          <Link to="/hats" className="hr-stat-cell">
            <span className="hr-stat-num">{totalHats}</span>
            <span className="hr-stat-cap">Hats</span>
          </Link>
          <Link to="/cases" className="hr-stat-cell">
            <span className="hr-stat-num">{totalCases}</span>
            <span className="hr-stat-cap">Cases</span>
          </Link>
          <Link to="/rooms" className="hr-stat-cell">
            <span className="hr-stat-num">{totalRooms}</span>
            <span className="hr-stat-cap">Rooms</span>
          </Link>
        </div>
        <div className="hr-stat-sub">
          <Link to="/cases?type=archive"><b>{archiveCases}</b> Archive</Link>
          <Link to="/cases?type=daily_wear"><b>{dailyCases}</b> Daily</Link>
          <Link to="/stats" className="hr-stat-sub-cta">All stats →</Link>
        </div>
      </nav>

      <div className="card hr-feature mb-3">
        <div className="card-body">
          <div className="d-flex justify-content-between align-items-start gap-2 flex-wrap mb-3">
            <div style={{ minWidth: 0 }}>
              <div className="card-title mb-1">Valuation Overview</div>
              <div className="text-secondary small">
                {valuation.valued > 0
                  ? <>Estimated sale value of {valuation.valued} of {valuation.total} hats.</>
                  : <>No priced hats yet — upload a photo with Claude configured, or enter prices by hand.</>
                }
              </div>
            </div>
            <Link to="/valuation" className="btn btn-outline-primary btn-sm">
              Full breakdown →
            </Link>
          </div>

          {valuation.valued > 0 && (
            <>
              <StatTiles tiles={[
                {
                  label: 'Paid',
                  value: money(valuation.spentTotal),
                  tone: 'purple',
                  sub: valuation.costUnknown > 0
                    ? `${valuation.spentCount} of ${valuation.total} known`
                    : 'all hats',
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
                  sub: valuation.retentionPct != null
                    ? `${valuation.retentionPct}% of retail`
                    : undefined,
                },
                {
                  label: 'Cases',
                  value: money(caseValue.retailTotal),
                  tone: 'cyan',
                  sub: `${caseValue.count} at replacement cost`,
                },
                {
                  // The question this page gets asked is "what's it all
                  // worth", and a Cases tile beside a hats-only total answers
                  // it only if you do the addition yourself.
                  label: 'Everything',
                  value: money(valuation.marketTotal + caseValue.retailTotal),
                  tone: 'pink',
                  sub: 'hats + cases',
                },
                {
                  label: 'vs. paid',
                  value: valuation.unrealizedGain != null
                    ? `${valuation.unrealizedGain >= 0 ? '+' : '−'}${money(Math.abs(valuation.unrealizedGain))}`
                    : '—',
                  tone: valuation.unrealizedGain != null && valuation.unrealizedGain >= 0 ? 'cyan' : 'muted',
                  sub: valuation.unrealizedGain != null
                    ? 'where cost is known'
                    : 'no purchase prices yet',
                },
              ]} />
              <p className="text-muted small mb-0 mt-3" style={{ fontSize: '0.72rem', lineHeight: 1.5 }}>
                Sale value is an estimate from asking prices, discounted for
                condition — not a quote. <Link to="/valuation">See how it's worked out</Link>.
              </p>
            </>
          )}
        </div>
      </div>

      {visibleHats.length > 0 && (
        <div
          className="hr-carousel mb-3"
          onTouchStart={handleTouchStart}
          onTouchEnd={handleTouchEnd}
        >
          <div className="hr-carousel-track">
            {visibleHats.map(hat => (
              <div
                key={hat.id}
                className="hr-carousel-slide"
                onClick={() => navigate(`/hats/${hat.id}`)}
                style={{ cursor: 'pointer' }}
              >
                <img
                  src={`/uploads/${hat.photo_path}`}
                  alt={hat.display_id || `Hat #${hat.id}`}
                />
                <div className="carousel-caption">
                  <h6>{hat.display_id || `Hat #${hat.id}`}</h6>
                  <small>{hat.style.replace(/_/g, ' ')}</small>
                </div>
              </div>
            ))}
          </div>
          {canPage && (
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
