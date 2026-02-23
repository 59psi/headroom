import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { listCases } from '../api/cases';
import { listHats } from '../api/hats';
import { listRooms } from '../api/rooms';
import { getLogo } from '../api/settings';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

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
  const hats = useQuery({ queryKey: ['hats'], queryFn: () => listHats() });
  const rooms = useQuery({ queryKey: ['rooms'], queryFn: listRooms });
  const logo = useQuery({ queryKey: ['settings', 'logo'], queryFn: getLogo });
  const navigate = useNavigate();
  const [activeIndex, setActiveIndex] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const hatsWithPhotos = useMemo(
    () => shuffleArray(hats.data?.filter(h => h.photo_path) ?? []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [hats.dataUpdatedAt]
  );

  const goNext = useCallback(() => {
    if (hatsWithPhotos.length <= 1) return;
    setActiveIndex(prev => (prev + 1) % hatsWithPhotos.length);
  }, [hatsWithPhotos.length]);

  const goPrev = useCallback(() => {
    if (hatsWithPhotos.length <= 1) return;
    setActiveIndex(prev => (prev - 1 + hatsWithPhotos.length) % hatsWithPhotos.length);
  }, [hatsWithPhotos.length]);

  // Auto-advance every 5 seconds
  useEffect(() => {
    if (hatsWithPhotos.length <= 1) return;
    intervalRef.current = setInterval(goNext, 5000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [hatsWithPhotos.length, goNext]);

  // Reset timer on manual navigation
  const resetTimer = useCallback(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    if (hatsWithPhotos.length > 1) {
      intervalRef.current = setInterval(goNext, 5000);
    }
  }, [hatsWithPhotos.length, goNext]);

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
            <div className="col-6 col-md-3 mb-3">
              <div className="fs-4 fw-semibold">{totalRooms}</div>
              <div className="text-secondary small">Rooms</div>
            </div>
          </div>
        </div>
      </div>

      {hatsWithPhotos.length > 0 && (
        <div className="mb-3 hr-carousel position-relative overflow-hidden rounded" style={{ cursor: 'pointer' }}>
          <div
            onClick={() => navigate(`/hats/${hatsWithPhotos[activeIndex].id}`)}
          >
            <img
              src={`/uploads/${hatsWithPhotos[activeIndex].photo_path}`}
              alt={hatsWithPhotos[activeIndex].display_id || `Hat #${hatsWithPhotos[activeIndex].id}`}
              className="d-block w-100"
              style={{ aspectRatio: '16/9', objectFit: 'cover' }}
            />
            <div className="carousel-caption">
              <h6 className="mb-0">{hatsWithPhotos[activeIndex].display_id || `Hat #${hatsWithPhotos[activeIndex].id}`}</h6>
              <small>{hatsWithPhotos[activeIndex].style.replace(/_/g, ' ')}</small>
            </div>
          </div>
          {hatsWithPhotos.length > 1 && (
            <>
              <button
                className="carousel-control-prev"
                type="button"
                onClick={(e) => { e.stopPropagation(); goPrev(); resetTimer(); }}
              >
                <span className="carousel-control-prev-icon" />
              </button>
              <button
                className="carousel-control-next"
                type="button"
                onClick={(e) => { e.stopPropagation(); goNext(); resetTimer(); }}
              >
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
