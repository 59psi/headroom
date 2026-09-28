import { useQuery } from '@tanstack/react-query';
import { ErrorNote } from '../components/common/ErrorNote';
import { Link } from 'react-router';
import { listCases } from '../api/cases';
import { listAllHats } from '../api/hats';
import { listRooms } from '../api/rooms';
import { getLogo } from '../api/settings';
import { logoSrc } from '../lib/photo';
import { StatTiles, StatTilesSkeleton } from '../components/charts/Charts';
import { Panel } from '../components/ui/Panel';
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

  // Nothing to page to when every hat is already on screen. Generalizes the
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

  // The hero is not data: it renders the moment the page does, whatever the
  // queries below are doing, so the first paint is the app rather than a
  // spinner in an empty frame. The two ways into the collection sit in it,
  // on the first screen of a phone — they used to be at the very bottom,
  // under the carousel.
  const hero = (
    <div className="hr-hero hr-cp-hero mb-3">
      {logoSrc(logo.data) && (
        <img src={logoSrc(logo.data)!} alt="" className="hr-logo" />
      )}
      <h1>Headroom</h1>
      <p>The Outrun-grade vault for your hat collection.</p>
      <div className="hr-cp-hero-actions">
        <Link to="/hats/new" className="btn btn-primary">Add hat</Link>
        <Link to="/cases/new" className="btn btn-outline-secondary">Add case</Link>
      </div>
    </div>
  );

  // A failed fetch must not render as an empty collection. `?? []` turns a
  // 500 or a dropped connection into "$0 across 0 hats", which is a confident
  // wrong answer — the exact thing `valueHat` returns `null` rather than 0 to
  // avoid. Errors are shown, not averaged in. "Try again" refetches in place
  // rather than asking for a reload of the whole app.
  if (cases.isError || hats.isError) {
    const retrying = cases.isFetching || hats.isFetching;
    return (
      <>
        {hero}
        <div className="alert alert-danger hr-cp-error" role="alert">
          <span>Couldn&rsquo;t load your collection.</span>
          <button
            type="button"
            className="btn btn-sm btn-outline-secondary"
            onClick={() => { void cases.refetch(); void hats.refetch(); }}
            disabled={retrying}
          >{retrying ? 'Retrying…' : 'Try again'}</button>
        </div>
      </>
    );
  }
  if (cases.isLoading || hats.isLoading) {
    return (
      <>
        {hero}
        <div className="hr-stat-rail hr-cp-rail-skel mb-3" aria-hidden="true">
          <span className="hr-skeleton" />
        </div>
        <Panel title="Valuation overview" featured>
          <StatTilesSkeleton count={4} label="Loading your collection…" />
        </Panel>
      </>
    );
  }

  const totalHats = hats.data?.length ?? 0;
  const totalCases = cases.data?.length ?? 0;
  // `rooms` and `logo` are not in the hard error guard above (the page is
  // useful without them), but a failed rooms load showed "0 Rooms" as if the
  // collection had none — so an unknown count is a dash, never a zero, and
  // the ErrorNote under the rail says why.
  const totalRooms = rooms.data ? String(rooms.data.length) : '–';
  const archiveCases = cases.data?.filter(c => c.case_type === 'archive').length ?? 0;
  const dailyCases = cases.data?.filter(c => c.case_type === 'daily_wear').length ?? 0;

  return (
    <>
      {hero}

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
        <ErrorNote of={[rooms, logo]} what="Some of the dashboard could not load" className="mt-2" />
        <div className="hr-stat-sub">
          <Link to="/cases?type=archive"><b>{archiveCases}</b> Archive</Link>
          <Link to="/cases?type=daily_wear"><b>{dailyCases}</b> Daily</Link>
          <Link to="/stats" className="hr-stat-sub-cta">All stats →</Link>
        </div>
      </nav>

      <Panel
        title="Valuation overview"
        featured
        description={
          valuation.valued > 0
            ? <>Estimated sale value of {valuation.valued} of {valuation.total} hats.</>
            : <>No priced hats yet — upload a photo with Claude configured, or enter prices by hand.</>
        }
        actions={
          <Link to="/valuation" className="btn btn-outline-secondary btn-sm">
            Full breakdown →
          </Link>
        }
      >
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
            <p className="hr-cp-note">
              Sale value is an estimate from live asking prices matched to
              each hat&rsquo;s own condition and size — not a quote.{' '}
              <Link to="/valuation">See how it&rsquo;s worked out</Link>.
            </p>
          </>
        )}
      </Panel>

      {visibleHats.length > 0 && (
        <div
          className="hr-carousel mb-3"
          onTouchStart={handleTouchStart}
          onTouchEnd={handleTouchEnd}
        >
          <div className="hr-carousel-track">
            {visibleHats.map(hat => (
              <Link
                key={hat.id}
                to={`/hats/${hat.id}`}
                className="hr-carousel-slide"
              >
                <img
                  src={`/uploads/${hat.photo_path}`}
                  alt={hat.display_id || `Hat #${hat.id}`}
                />
                {/* A caption, not a heading: an <h6> per slide put a
                    sixth-level heading straight under the page's h1. */}
                <div className="carousel-caption">
                  <span className="hr-cp-caption-id">{hat.display_id || `Hat #${hat.id}`}</span>
                  <small>{hat.style.replace(/_/g, ' ')}</small>
                </div>
              </Link>
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
    </>
  );
}
