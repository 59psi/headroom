import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
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
      <CaseCollage thumbs={c.hat_thumbs} label={c.display_id} />
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

/**
 * The hats inside a case, as a tile.
 *
 * Replaces a photo of the case itself, which was the same grey box in every
 * card — every case looks identical from the outside, so the picture carried
 * no information at the moment you were scanning for one. What you are
 * actually looking for is what's in it.
 *
 * The layout follows the count rather than forcing a 2x2: one hat fills the
 * tile, two split it, three or four make a grid. A fixed grid would letterbox
 * a single hat into a quarter of the space for the sake of symmetry.
 */
function CaseCollage({ thumbs, label }: { thumbs: string[]; label: string }) {
  if (thumbs.length === 0) {
    return (
      <div
        className="d-flex align-items-center justify-content-center text-muted"
        style={{ aspectRatio: '4/3', fontSize: '0.75rem' }}
      >
        empty
      </div>
    );
  }

  return (
    <div
      className="hr-case-collage"
      style={{
        aspectRatio: '4/3',
        display: 'grid',
        gap: 2,
        gridTemplateColumns: thumbs.length === 1 ? '1fr' : '1fr 1fr',
        // Three tiles would otherwise leave a hole; the first spans the top.
        gridTemplateRows: thumbs.length <= 2 ? '1fr' : '1fr 1fr',
      }}
    >
      {thumbs.map((path, i) => (
        <img
          key={path}
          src={`/uploads/${path}`}
          alt=""
          loading="lazy"
          style={{
            width: '100%',
            height: '100%',
            objectFit: 'contain',
            // With three hats the first one takes the whole top row, so the
            // grid reads as deliberate rather than as a missing fourth.
            gridColumn: thumbs.length === 3 && i === 0 ? 'span 2' : undefined,
          }}
        />
      ))}
      <span className="visually-hidden">{`Hats in ${label}`}</span>
    </div>
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
