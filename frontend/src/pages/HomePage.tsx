import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { listCases } from '../api/cases';
import { listHats } from '../api/hats';
import { LoadingSpinner } from '../components/common/LoadingSpinner';

export function HomePage() {
  const cases = useQuery({ queryKey: ['cases'], queryFn: listCases });
  const hats = useQuery({ queryKey: ['hats'], queryFn: () => listHats() });

  if (cases.isLoading || hats.isLoading) return <LoadingSpinner />;

  const totalHats = hats.data?.length ?? 0;
  const totalCases = cases.data?.length ?? 0;
  const archiveCases = cases.data?.filter(c => c.case_type === 'archive').length ?? 0;
  const dailyCases = cases.data?.filter(c => c.case_type === 'daily_wear').length ?? 0;

  return (
    <>
      <h1 className="mb-3">Headroom</h1>

      <div className="card mb-3">
        <div className="card-body">
          <h5 className="card-title mb-3">Collection Overview</h5>
          <div className="row text-center">
            <div className="col-6 col-md-3 mb-3">
              <div className="fs-2 fw-bold text-primary">{totalHats}</div>
              <div className="text-secondary small">Total Hats</div>
            </div>
            <div className="col-6 col-md-3 mb-3">
              <div className="fs-2 fw-bold text-primary">{totalCases}</div>
              <div className="text-secondary small">Total Cases</div>
            </div>
            <div className="col-6 col-md-3 mb-3">
              <div className="fs-4 fw-semibold">{archiveCases}</div>
              <div className="text-secondary small">Archive</div>
            </div>
            <div className="col-6 col-md-3 mb-3">
              <div className="fs-4 fw-semibold">{dailyCases}</div>
              <div className="text-secondary small">Daily Wear</div>
            </div>
          </div>
        </div>
      </div>

      <div className="d-flex gap-2">
        <Link to="/hats/new" className="btn btn-primary flex-fill">+ Add Hat</Link>
        <Link to="/cases/new" className="btn btn-outline-secondary flex-fill">+ Add Case</Link>
      </div>
    </>
  );
}
