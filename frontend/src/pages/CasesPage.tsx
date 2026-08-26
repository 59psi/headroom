import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router';
import { listCases } from '../api/cases';
import { getRoomOptions } from '../api/rooms';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import type { CaseRead } from '../types';
import { CaseCollage } from '../components/cases/CaseCollage';

function CaseCard({ c }: { c: CaseRead }) {
  const typeLabel = c.case_type === 'archive' ? 'Archive' : 'Daily Wear';

  let countLabel: string;
  if (c.hat_count === 0) {
    countLabel = 'Empty';
  } else if (c.beanie_count > 0) {
    countLabel = `${c.beanie_count} beanie${c.beanie_count !== 1 ? 's' : ''}`;
  } else {
    countLabel = `${c.regular_count} hat${c.regular_count !== 1 ? 's' : ''}`;
  }
  // Full and overfull are different states and the grid is where you'd notice
  // either. A bare count can't say which: "4 hats" looks identical whether the
  // case holds four comfortably or has one crammed in.
  //
  // Asked of the type the case actually HOLDS. Cases are type-exclusive, so
  // the unused type's `free_*` sits at its full nominal figure forever —
  // `free_regular + free_beanie === 0` therefore could never be true for a
  // case with regular hats in it (a full 3-hat case publishes
  // `free_regular: 0, free_beanie: 6`), and the badge only ever appeared on
  // beanie cases.
  const isFull = c.beanie_count > 0 ? c.free_beanie === 0 : c.free_regular === 0;
  const fillLabel = c.overfull ? 'overfull' : (c.hat_count > 0 && isFull ? 'full' : null);

  return (
    <Link to={`/cases/${c.display_id}`} className="card text-decoration-none h-100">
      <CaseCollage thumbs={c.hat_thumbs} label={c.display_id} />
      <div className="card-body d-flex justify-content-between align-items-center gap-2">
        <div>
          <div className="font-mono fw-bold fs-5" style={{ color: 'var(--neon-cyan)' }}>{c.display_id}</div>
          <div className="text-secondary small">{typeLabel} · {c.room_name}</div>
        </div>
        <div className="text-end">
          <div className="font-mono fw-semibold" style={{ color: 'var(--neon-pink)' }}>{countLabel}</div>
          {fillLabel && (
            <div className={`hr-fill-tag${c.overfull ? ' is-overfull' : ''}`}>{fillLabel}</div>
          )}
        </div>
      </div>
    </Link>
  );
}

type CaseTypeFilter = 'all' | 'archive' | 'daily_wear';

export function CasesPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ['cases'], queryFn: listCases });
  const roomsQ = useQuery({ queryKey: ['meta', 'rooms'], queryFn: getRoomOptions });
  // The type filter lives in the URL so the home page's Archive/Daily counts
  // can link straight to the filtered list, and so a filtered view survives a
  // reload or being shared. The buttons below write to the same place, which
  // keeps one source of truth instead of a URL and a useState that can differ.
  const [params, setParams] = useSearchParams();
  const rawType = params.get('type');
  const typeFilter: CaseTypeFilter =
    rawType === 'archive' || rawType === 'daily_wear' ? rawType : 'all';
  const setTypeFilter = (next: CaseTypeFilter) => {
    // `replace` so tapping through the three filters doesn't build a back
    // stack that has to be unwound one press at a time to leave the page.
    setParams(
      prev => {
        const out = new URLSearchParams(prev);
        if (next === 'all') out.delete('type'); else out.set('type', next);
        return out;
      },
      { replace: true },
    );
  };
  const [roomFilter, setRoomFilter] = useState('');

  if (isLoading) return <LoadingSpinner />;
  if (error) return (
    <div className="text-center py-5">
      <h5 className="mb-2">No cases to display</h5>
      <p className="text-secondary small mb-3">The case collection is empty or could not be loaded.</p>
      <Link to="/cases/new" className="btn btn-primary">Create First Case</Link>
    </div>
  );

  const filtered = data?.filter(c => {
    if (typeFilter !== 'all' && c.case_type !== typeFilter) return false;
    if (roomFilter && c.room_id !== Number(roomFilter)) return false;
    return true;
  }) ?? [];

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3 gap-2 flex-wrap">
        <h1>Cases</h1>
        <div className="d-flex gap-2">
          <a href="/api/admin/case-labels" target="_blank" rel="noopener noreferrer" className="btn btn-outline-secondary btn-sm" title="Printable QR labels for every case">🏷 Labels</a>
          <Link to="/cases/new" className="btn btn-primary btn-sm">+ New</Link>
        </div>
      </div>

      <div className="d-flex gap-2 mb-3 flex-wrap">
        <div className="btn-group flex-grow-1" role="group">
          <button
            type="button"
            className={`btn btn-sm ${typeFilter === 'all' ? 'btn-primary' : 'btn-outline-primary'}`}
            onClick={() => setTypeFilter('all')}
          >All</button>
          <button
            type="button"
            className={`btn btn-sm ${typeFilter === 'archive' ? 'btn-primary' : 'btn-outline-primary'}`}
            onClick={() => setTypeFilter('archive')}
          >Archive</button>
          <button
            type="button"
            className={`btn btn-sm ${typeFilter === 'daily_wear' ? 'btn-primary' : 'btn-outline-primary'}`}
            onClick={() => setTypeFilter('daily_wear')}
          >Daily Wear</button>
        </div>
        <select
          aria-label="Room"
          className="form-select form-select-sm"
          style={{ maxWidth: 180 }}
          value={roomFilter}
          onChange={e => setRoomFilter(e.target.value)}
        >
          <option value="">All Rooms</option>
          {roomsQ.data?.map(r => (
            <option key={r.value} value={r.value}>{r.label}</option>
          ))}
        </select>
      </div>

      {!filtered.length ? (
        <div className="text-center py-5 text-secondary">
          <p className="mb-3">{data?.length ? 'No matching cases' : 'No cases yet'}</p>
          {!data?.length && <Link to="/cases/new" className="btn btn-primary">Create First Case</Link>}
        </div>
      ) : (
        <div className="row row-cols-1 row-cols-md-2 row-cols-lg-3 g-3">
          {filtered.map(c => (
            <div className="col" key={c.id}><CaseCard c={c} /></div>
          ))}
        </div>
      )}
    </>
  );
}
