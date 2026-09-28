import { useQuery } from '@tanstack/react-query';
import { ErrorNote } from '../components/common/ErrorNote';
import { LoadError } from '../components/common/LoadError';
import { Link } from 'react-router';
import { listCases } from '../api/cases';
import { listAllHats } from '../api/hats';
import { listRooms } from '../api/rooms';
import { getLogo } from '../api/settings';
import { logoSrc, uploadUrl } from '../lib/photo';
import { useHatLabels } from '../lib/labels';
import { hatName } from '../lib/placement';
import { qk } from '../lib/queryKeys';
import { CASE_TYPES } from '../lib/caseTypes';
import { StatTiles, StatTilesSkeleton } from '../components/charts/Charts';
import { Panel } from '../components/ui/Panel';
import { money, valueCases, valueCollection } from '../lib/valuation';
import { plural } from '../lib/format';
import { useMediaQuery } from '../lib/useMediaQuery';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

/** Desktop, as this app already defines it — the width where TopNav appears. */
const TWO_UP_QUERY = '(min-width: 992px)';

/** How long each screenful of the carousel stays up while it plays. */
export const CAROUSEL_STEP_MS = 5000;

function shuffleArray<T>(arr: T[]): T[] {
  const shuffled = [...arr];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled;
}

export function HomePage() {
  const cases = useQuery({ queryKey: qk.cases(), queryFn: listCases });
  const hats = useQuery({ queryKey: qk.hats(), queryFn: listAllHats });
  const rooms = useQuery({ queryKey: qk.rooms(), queryFn: listRooms });
  const logo = useQuery({ queryKey: qk.settings.logo(), queryFn: getLogo });
  const labels = useHatLabels();
  const [activeIndex, setActiveIndex] = useState(0);
  const touchStartX = useRef<number | null>(null);
  const twoUp = useMediaQuery(TWO_UP_QUERY);

  // Whether the carousel moves on its own (WCAG 2.2.2, Pause, Stop, Hide).
  // It advanced every five seconds with no way to stop it, and ignored the
  // browser's "reduce motion" — the one setting a vestibular-sensitive
  // visitor has for saying so. Now: it does not start by itself when motion
  // is reduced; the visible Pause/Play control overrides either way; and it
  // holds still while the pointer is over it or focus is inside it, so a
  // slide does not change under the hand reaching for it.
  const reduceMotion = useMediaQuery('(prefers-reduced-motion: reduce)');
  const [playChoice, setPlayChoice] = useState<'auto' | 'playing' | 'paused'>('auto');
  const [held, setHeld] = useState({ hover: false, focus: false });

  const withPhotos = useMemo(
    () => hats.data?.filter(h => h.photo_path) ?? [],
    [hats.data]
  );
  // Reshuffle only when the SET of hats changes, not on every refetch.
  // `dataUpdatedAt` ticks on each poll even when the payload is identical, so
  // keying on it reshuffled the deck and made the visible hat jump at random.
  // So the ORDER is shuffled from the id set alone, and the current rows are
  // laid into it: a refetch with the same hats keeps the order and still
  // shows each hat as it now is (a new photo, a new style), which the
  // shuffled copy of the old rows did not.
  const photoKey = withPhotos.map(h => h.id).join(',');
  const order = useMemo(() => shuffleArray(photoKey ? photoKey.split(',') : []), [photoKey]);
  const hatsWithPhotos = useMemo(() => {
    const byId = new Map(withPhotos.map(h => [String(h.id), h]));
    return order.flatMap(id => byId.get(id) ?? []);
  }, [order, withPhotos]);
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

  const playing = playChoice === 'playing' || (playChoice === 'auto' && !reduceMotion);
  const advancing = canPage && playing && !held.hover && !held.focus;

  // One step per screenful, restarted whenever the screenful changes — so an
  // arrow or a swipe gives the new slide its full time rather than whatever
  // was left on a running interval.
  useEffect(() => {
    if (!advancing) return;
    const step = setTimeout(goNext, CAROUSEL_STEP_MS);
    return () => clearTimeout(step);
  }, [advancing, goNext, activeIndex]);

  function handleTouchStart(e: React.TouchEvent) {
    touchStartX.current = e.touches[0].clientX;
  }

  function handleTouchEnd(e: React.TouchEvent) {
    if (touchStartX.current === null) return;
    const dx = e.changedTouches[0].clientX - touchStartX.current;
    if (Math.abs(dx) > 40) {
      if (dx < 0) goNext(); else goPrev();
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
    return (
      <>
        {hero}
        <LoadError what="Couldn’t load your collection." queries={[cases, hats]} />
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
  // One count per case type, from the one table of them — each links to the
  // Cases page's own filter for that type.
  const typeCounts = CASE_TYPES.map(t => ({
    ...t,
    count: cases.data?.filter(c => c.case_type === t.value).length ?? 0,
  }));

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
          {typeCounts.map(t => (
            <Link key={t.value} to={`/cases?type=${t.value}`}><b>{t.count}</b> {t.label}</Link>
          ))}
          <Link to="/stats" className="hr-stat-sub-cta">All stats →</Link>
        </div>
      </nav>

      <Panel
        title="Valuation overview"
        featured
        description={
          valuation.valued > 0
            ? <>Estimated sale value of {valuation.valued} of {plural(valuation.total, 'hat')}.</>
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
          role="group"
          aria-roledescription="carousel"
          aria-label="Hats from the collection"
          onTouchStart={handleTouchStart}
          onTouchEnd={handleTouchEnd}
          onMouseEnter={() => setHeld(h => ({ ...h, hover: true }))}
          onMouseLeave={() => setHeld(h => ({ ...h, hover: false }))}
          onFocus={() => setHeld(h => ({ ...h, focus: true }))}
          // Only when focus has left the carousel altogether — moving from
          // one slide to an arrow is still "inside".
          onBlur={e => {
            if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
              setHeld(h => ({ ...h, focus: false }));
            }
          }}
        >
          <div className="hr-carousel-track" aria-live={advancing ? 'off' : 'polite'}>
            {visibleHats.map(hat => (
              <Link
                key={hat.id}
                to={`/hats/${hat.id}`}
                className="hr-carousel-slide"
              >
                <img src={uploadUrl(hat.photo_path)} alt={hatName(hat)} />
                {/* A caption, not a heading: an <h6> per slide put a
                    sixth-level heading straight under the page's h1. */}
                <div className="carousel-caption">
                  <span className="hr-cp-caption-id">{hatName(hat)}</span>
                  <small>{labels.style(hat.style)}</small>
                </div>
              </Link>
            ))}
          </div>
          {canPage && (
            <>
              <button
                className="carousel-control-prev"
                type="button"
                onClick={(e) => { e.stopPropagation(); goPrev(); }}
                aria-label="Previous"
              >
                <span className="carousel-control-prev-icon" />
              </button>
              <button
                className="carousel-control-next"
                type="button"
                onClick={(e) => { e.stopPropagation(); goNext(); }}
                aria-label="Next"
              >
                <span className="carousel-control-next-icon" />
              </button>
              <button
                className="hr-carousel-pause"
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setPlayChoice(playing ? 'paused' : 'playing');
                  // Play is an explicit request, and it outranks the holds:
                  // pressing it puts the pointer over the carousel and the
                  // focus inside it, so without this the button turned to
                  // "Pause" while nothing moved until both had left.
                  if (!playing) setHeld({ hover: false, focus: false });
                }}
                aria-label={playing ? 'Pause slideshow' : 'Play slideshow'}
                title={playing ? 'Pause slideshow' : 'Play slideshow'}
              >
                <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true" focusable="false">
                  {playing
                    ? <><rect x="4" y="3" width="3" height="10" rx="1" /><rect x="9" y="3" width="3" height="10" rx="1" /></>
                    : <path d="M5 3.5v9l7.5-4.5z" />}
                </svg>
              </button>
            </>
          )}
        </div>
      )}
    </>
  );
}
