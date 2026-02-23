import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { listCases } from '../api/cases';
import { listHats } from '../api/hats';
import { getLogo } from '../api/settings';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { useEffect, useRef } from 'react';

export function HomePage() {
  const cases = useQuery({ queryKey: ['cases'], queryFn: listCases });
  const hats = useQuery({ queryKey: ['hats'], queryFn: () => listHats() });
  const logo = useQuery({ queryKey: ['settings', 'logo'], queryFn: getLogo });
  const carouselRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!carouselRef.current) return;
    const Carousel = (window as unknown as Record<string, unknown>).bootstrap as
      | { Carousel: new (el: HTMLElement, opts: Record<string, unknown>) => unknown }
      | undefined;
    if (Carousel) {
      new Carousel.Carousel(carouselRef.current, { ride: 'carousel', interval: 5000 });
    }
  }, [hats.data]);

  if (cases.isLoading || hats.isLoading) return <LoadingSpinner />;

  const totalHats = hats.data?.length ?? 0;
  const totalCases = cases.data?.length ?? 0;
  const archiveCases = cases.data?.filter(c => c.case_type === 'archive').length ?? 0;
  const dailyCases = cases.data?.filter(c => c.case_type === 'daily_wear').length ?? 0;

  const hatsWithPhotos = hats.data?.filter(h => h.photo_path) ?? [];

  return (
    <>
      <div className="hr-hero mb-3">
        {logo.data?.logo_path && (
          <img src={`/uploads/${logo.data.logo_path}`} alt="" className="hr-logo" />
        )}
        <h1 className="mb-1">Headroom</h1>
        <p className="mb-0 opacity-75">Your hat collection, organized.</p>
      </div>

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

      {hatsWithPhotos.length > 0 && (
        <div
          ref={carouselRef}
          id="homeCarousel"
          className="carousel slide mb-3 hr-carousel"
          data-bs-ride="carousel"
          data-bs-interval="5000"
        >
          <div className="carousel-inner">
            {hatsWithPhotos.map((h, i) => (
              <div
                key={h.id}
                className={`carousel-item${i === 0 ? ' active' : ''}`}
                style={{ cursor: 'pointer' }}
                onClick={() => navigate(`/hats/${h.id}`)}
              >
                <img
                  src={`/uploads/${h.photo_path}`}
                  alt={h.display_id || `Hat #${h.id}`}
                  className="d-block w-100"
                  style={{ aspectRatio: '16/9', objectFit: 'cover' }}
                />
                <div className="carousel-caption">
                  <h6 className="mb-0">{h.display_id || `Hat #${h.id}`}</h6>
                  <small>{h.style.replace(/_/g, ' ')}</small>
                </div>
              </div>
            ))}
          </div>
          {hatsWithPhotos.length > 1 && (
            <>
              <button className="carousel-control-prev" type="button" data-bs-target="#homeCarousel" data-bs-slide="prev">
                <span className="carousel-control-prev-icon" />
              </button>
              <button className="carousel-control-next" type="button" data-bs-target="#homeCarousel" data-bs-slide="next">
                <span className="carousel-control-next-icon" />
              </button>
            </>
          )}
        </div>
      )}

      <div className="d-flex gap-2">
        <Link to="/hats/new" className="btn btn-primary flex-fill">+ Add Hat</Link>
        <Link to="/cases/new" className="btn btn-outline-secondary flex-fill">+ Add Case</Link>
      </div>
    </>
  );
}
