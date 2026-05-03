import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { listCases } from '../api/cases';
import { getRoomOptions } from '../api/rooms';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import type { CaseRead } from '../types';

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

  return (
    <Link to={`/cases/${c.display_id}`} className="card text-decoration-none h-100">
      {c.photo_path && (
        <img
          src={`/uploads/${c.photo_path}`}
          alt={c.display_id}
          className="hr-photo-raster"
          style={{ width: '100%', aspectRatio: '4/3', display: 'block' }}
        />
      )}
      <div className="card-body d-flex justify-content-between align-items-center gap-2">
        <div>
          <div className="font-mono fw-bold fs-5" style={{ color: 'var(--neon-cyan)' }}>{c.display_id}</div>
          <div className="text-secondary small">{typeLabel} · {c.room_name}</div>
        </div>
        <div className="text-end">
          <div className="font-mono fw-semibold" style={{ color: 'var(--neon-pink)' }}>{countLabel}</div>
        </div>
      </div>
    </Link>
  );
}

export function CasesPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ['cases'], queryFn: listCases });
  const roomsQ = useQuery({ queryKey: ['meta', 'rooms'], queryFn: getRoomOptions });
  const [typeFilter, setTypeFilter] = useState<'all' | 'archive' | 'daily_wear'>('all');
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
        <Link to="/cases/new" className="btn btn-primary btn-sm">+ New</Link>
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
