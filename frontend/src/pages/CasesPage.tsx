import { useMemo, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router';
import { listCases } from '../api/cases';
import { getRoomOptions } from '../api/rooms';
import { caseLabelsUrl } from '../api/settings';
import { CaseGridSkeleton, CaseTile } from '../components/cases/CaseTile';
import { ErrorNote } from '../components/common/ErrorNote';
import { LoadError } from '../components/common/LoadError';
import { PageHeader } from '../components/ui/PageHeader';
import { Segmented } from '../components/ui/Segmented';
import { DEFAULT_BEANIE_CAPACITY, DEFAULT_REGULAR_CAPACITY } from '../lib/capacity';
import { CASE_TYPES, isCaseType, type CaseType } from '../lib/caseTypes';
import { plural } from '../lib/format';
import { qk } from '../lib/queryKeys';

type CaseTypeFilter = 'all' | CaseType;

/** "All", then one segment per case type — from the one table of them. */
const TYPE_FILTERS: ReadonlyArray<{ value: CaseTypeFilter; label: string }> = [
  { value: 'all', label: 'All' },
  ...CASE_TYPES.map(t => ({ value: t.value, label: t.label })),
];

export function CasesPage() {
  const casesQ = useQuery({ queryKey: qk.cases(), queryFn: listCases });
  const { data, isLoading, error } = casesQ;
  const roomsQ = useQuery({ queryKey: qk.meta.rooms(), queryFn: getRoomOptions });
  // The type filter lives in the URL so the home page's Archive/Daily counts
  // can link straight to the filtered list, and so a filtered view survives a
  // reload or being shared. The buttons below write to the same place, which
  // keeps one source of truth instead of a URL and a useState that can differ.
  // The room filter joined it for the same reasons: it was a `useState` and
  // was the one filter a reload threw away.
  const [params, setParams] = useSearchParams();
  const rawType = params.get('type');
  const typeFilter: CaseTypeFilter = isCaseType(rawType) ? rawType : 'all';
  const rawRoom = params.get('room') ?? '';
  // A `?room=` from an old link can name a room that has since been deleted.
  // Applied as-is it filters to nothing while the select — with no option for
  // that id — shows "All rooms": an empty grid under a filter that claims to
  // be off. Once the options are in, an unknown id is ignored.
  const roomFilter = rawRoom && (!roomsQ.data || roomsQ.data.some(r => String(r.value) === rawRoom))
    ? rawRoom
    : '';

  const setFilter = (key: 'type' | 'room', value: string) => {
    // `replace` so tapping through the filters doesn't build a back stack
    // that has to be unwound one press at a time to leave the page.
    setParams(
      prev => {
        const out = new URLSearchParams(prev);
        if (!value || value === 'all') out.delete(key); else out.set(key, value);
        return out;
      },
      { replace: true },
    );
  };
  const clearFilters = () => {
    setParams(
      prev => {
        const out = new URLSearchParams(prev);
        out.delete('type');
        out.delete('room');
        return out;
      },
      { replace: true },
    );
  };

  // Counts on the type segments are taken AFTER the room filter, so each
  // number is what tapping that segment would show.
  const inRoom = useMemo(
    () => (data ?? []).filter(c => !roomFilter || c.room_id === Number(roomFilter)),
    [data, roomFilter],
  );
  const typeCounts = useMemo(() => {
    const counts = Object.fromEntries(
      TYPE_FILTERS.map(f => [f.value, f.value === 'all' ? inRoom.length : 0]),
    ) as Record<CaseTypeFilter, number>;
    for (const c of inRoom) counts[c.case_type]++;
    return counts;
  }, [inRoom]);
  const hatTotal = useMemo(() => (data ?? []).reduce((n, c) => n + c.hat_count, 0), [data]);

  const filtered = typeFilter === 'all' ? inRoom : inRoom.filter(c => c.case_type === typeFilter);
  const filtering = typeFilter !== 'all' || !!roomFilter;

  let body: ReactNode;
  if (error) {
    // Same rule as Home/Valuation/Stats: a failed fetch is an error, not an
    // empty collection with a "create your first one" call to action — and
    // the retry is a refetch in place. This page said "Reload to try again"
    // with no button, which restarts the whole app to refetch one list.
    body = <LoadError what="Couldn’t load your cases." queries={[casesQ]} />;
  } else if (isLoading || !data) {
    body = <CaseGridSkeleton />;
  } else if (!data.length) {
    body = (
      <div className="hr-cr-empty">
        <p className="hr-cr-empty-title">No cases yet</p>
        <p className="hr-cr-empty-text">
          A case holds {DEFAULT_REGULAR_CAPACITY} hats or {DEFAULT_BEANIE_CAPACITY} beanies
          by default. Create one, then add hats to it.
        </p>
        <Link to="/cases/new" className="btn btn-primary">Create first case</Link>
      </div>
    );
  } else if (!filtered.length) {
    // Name the filter that emptied the grid. "This type and room together"
    // was said under a type filter alone, pointing at a room filter that was
    // not on.
    const typeName = TYPE_FILTERS.find(f => f.value === typeFilter)?.label.toLowerCase();
    const why = typeFilter !== 'all' && roomFilter
      ? 'Nothing fits this type and room together.'
      : roomFilter
        ? 'No cases in this room yet.'
        : `No ${typeName} cases yet.`;
    body = (
      <div className="hr-cr-empty">
        <p className="hr-cr-empty-title">No matching cases</p>
        <p className="hr-cr-empty-text">{why}</p>
        <button type="button" className="btn btn-outline-secondary" onClick={clearFilters}>
          Clear filters
        </button>
      </div>
    );
  } else {
    body = (
      <div className="hr-case-grid">
        {filtered.map(c => <CaseTile key={c.id} c={c} />)}
      </div>
    );
  }

  return (
    <>
      <PageHeader
        title="Cases"
        summary={data && data.length > 0 && (
          <>
            {plural(data.length, 'case')} · {plural(hatTotal, 'hat')}
            {filtering && <> · showing {filtered.length}</>}
          </>
        )}
        actions={
          <>
            <a
              href={caseLabelsUrl()}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-outline-secondary btn-sm"
              title="Printable QR labels for every case"
            >
              <TagIcon /> Labels
            </a>
            <Link to="/cases/new" className="btn btn-primary btn-sm">
              <PlusIcon /> New case
            </Link>
          </>
        }
      />

      {!error && (
        <div className="hr-cr-toolbar">
          {/* Equal segments across the phone's width. The counts wait for the
              data rather than showing a row of zeros while it loads. */}
          <Segmented
            label="Case type"
            fill
            options={TYPE_FILTERS.map(f => ({ ...f, count: data ? typeCounts[f.value] : undefined }))}
            value={typeFilter}
            onChange={v => setFilter('type', v)}
          />
          <select
            aria-label="Room"
            className="form-select"
            value={roomFilter}
            onChange={e => setFilter('room', e.target.value)}
          >
            <option value="">All rooms</option>
            {roomsQ.data?.map(r => (
              <option key={r.value} value={r.value}>{r.label}</option>
            ))}
          </select>
        </div>
      )}
      {/* A failed room list is a filter offering only "All rooms", which
          reads as a collection with no rooms in it. */}
      {!error && <ErrorNote of={roomsQ} what="Could not load the room filter" className="mb-3" />}

      {body}
    </>
  );
}

function TagIcon() {
  return (
    <svg className="hr-cr-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      <path d="M2 2.75v4.5c0 .4.16.78.44 1.06l5.25 5.25a1.5 1.5 0 0 0 2.12 0l4.5-4.5a1.5 1.5 0 0 0 0-2.12L9.06 1.69A1.5 1.5 0 0 0 8 1.25H3.5A1.5 1.5 0 0 0 2 2.75Z" />
      <circle cx="5.25" cy="4.75" r="1" fill="currentColor" stroke="none" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg className="hr-cr-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <path d="M8 3v10M3 8h10" />
    </svg>
  );
}
