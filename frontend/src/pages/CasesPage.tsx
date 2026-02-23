import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { listCases } from '../api/cases';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import type { CaseRead } from '../types';

function CaseCard({ c }: { c: CaseRead }) {
  const typeLabel = c.case_type === 'archive' ? 'Archive' : 'Daily Wear';
  return (
    <Link to={`/cases/${c.display_id}`} className="card mb-2 text-decoration-none text-body">
      {c.photo_path && (
        <img src={`/uploads/${c.photo_path}`} alt={c.display_id} className="card-img-top" style={{ aspectRatio: '4/3', objectFit: 'cover' }} />
      )}
      <div className="card-body d-flex justify-content-between align-items-center">
        <div>
          <div className="fw-bold fs-5">{c.display_id}</div>
          <div className="text-secondary small">{typeLabel}</div>
        </div>
        <div className="text-end">
          <div className="fw-semibold">{c.hat_count} hats</div>
          <div className="text-secondary small">{c.regular_count}R / {c.beanie_count}B</div>
        </div>
      </div>
    </Link>
  );
}

export function CasesPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ['cases'], queryFn: listCases });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <div className="alert alert-danger">{String(error)}</div>;

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h1>Cases</h1>
        <Link to="/cases/new" className="btn btn-primary">+ New</Link>
      </div>
      {!data?.length ? (
        <div className="text-center py-5 text-secondary">
          <p className="mb-3">No cases yet</p>
          <Link to="/cases/new" className="btn btn-primary">Create First Case</Link>
        </div>
      ) : (
        <div className="row row-cols-1 row-cols-md-2 row-cols-lg-3 g-3">
          {data.map(c => (
            <div className="col" key={c.id}><CaseCard c={c} /></div>
          ))}
        </div>
      )}
    </>
  );
}
