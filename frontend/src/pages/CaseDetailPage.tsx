import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate, Link } from 'react-router';
import { getCase, deleteCase } from '../api/cases';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { tileSrc } from '../lib/photo';
import { CaseCollage } from '../components/cases/CaseCollage';
import { invalidateHatViews } from '../lib/invalidate';
import { TagUrlRow } from '../components/common/TagUrlRow';

export function CaseDetailPage() {
  const { displayId } = useParams<{ displayId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ['case', displayId],
    queryFn: () => getCase(displayId!),
    enabled: !!displayId,
  });

  const removeMutation = useMutation({
    mutationFn: () => deleteCase(displayId!),
    // Deleting a case UNASSIGNS every hat in it (case_service.delete_case sets
    // case_id = None), so this changes hats, not just cases — `['hats']` and
    // `['rooms']` were both left stale by invalidating `['cases']` alone.
    onSuccess: () => {
      invalidateHatViews(qc);
      navigate('/cases');
    },
  });


  if (isLoading) return <LoadingSpinner />;
  if (error || !data) return (
    <div className="text-center py-5">
      <h5 className="mb-2">Case not found</h5>
      <p className="text-secondary small mb-3">This case may have been deleted or doesn't exist.</p>
      <Link to="/cases" className="btn btn-outline-primary">← Back to Cases</Link>
    </div>
  );

  const typeLabel = data.case_type === 'archive' ? 'Archive' : 'Daily Wear';

  // Served, never restated here. These were `data.capacity ?? 6` and
  // `?? 4` — a second copy of a rule `services/capacity.py` owns, and wrong
  // twice: 4 is the OVERFILL limit rather than nominal capacity, so a full
  // three-hat case displayed "3/4" and invited an add the API would accept
  // only as overfull; and the hardcoded 6 became wrong the moment beanie
  // capacity moved to 8.
  const maxBeanies = data.nominal_beanie;
  const maxRegular = data.nominal_regular;

  let capacityDisplay: React.ReactNode;
  if (data.hat_count === 0) {
    capacityDisplay = (
      <div className="text-center text-muted small">
        {data.capacity
          ? `Empty — holds ${data.capacity}`
          : `Empty — holds ${maxRegular} hats or ${maxBeanies} beanies`}
      </div>
    );
  } else if (data.beanie_count > 0) {
    capacityDisplay = (
      <div className="text-center">
        <div className="font-display" style={{ fontSize: '1.4rem', color: 'var(--neon-pink)' }}>{data.beanie_count}/{maxBeanies}</div>
        <div className="hr-tier-label">Beanies</div>
      </div>
    );
  } else {
    capacityDisplay = (
      <div className="text-center">
        <div className="font-display" style={{ fontSize: '1.4rem', color: 'var(--neon-pink)' }}>{data.regular_count}/{maxRegular}</div>
        <div className="hr-tier-label">Hats</div>
      </div>
    );
  }

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3 gap-2 flex-wrap">
        <h1 className="font-mono" style={{ color: 'var(--neon-cyan)' }}>{data.display_id}</h1>
        <div className="d-flex gap-2 align-items-center">
          <span className="badge bg-secondary">{typeLabel}</span>
          <span className="badge bg-info">{data.room_name}</span>
          <Link to={`/cases/${displayId}/edit`} className="btn btn-outline-secondary btn-sm">Edit</Link>
        </div>
      </div>

      {/* The hats, not a picture of the case. Every case looks identical from
          the outside, so a photo of one carried no information — and an EMPTY
          photo box was worse: a case with three hats in it showed a
          screen-filling "NO PHOTO" placeholder and pushed its actual contents
          below the fold. The grid switched to this collage; this page kept the
          uploader until now. */}
      <div className="card mb-3">
        <div className="card-body">
          <CaseCollage
            thumbs={data.hats.map(h => h.thumb_path || h.photo_path).filter((p): p is string => !!p).slice(0, 4)}
            label={data.display_id}
          />
          <div className="mt-3">{capacityDisplay}</div>
        </div>
      </div>

      <div className="d-flex justify-content-between align-items-center mb-2">
        <h5 className="mb-0">Hats in this case</h5>
        <Link to={`/hats/new?caseId=${data.id}`} className="btn btn-primary btn-sm">+ Add Hat</Link>
      </div>

      {!data.hats.length ? (
        <div className="text-center py-4 text-secondary">
          <p className="mb-3">No hats in this case</p>
          <Link to={`/hats/new?caseId=${data.id}`} className="btn btn-primary">Add Hat</Link>
        </div>
      ) : (
        data.hats.map(h => (
          <Link key={h.id} to={`/hats/${h.id}`} className="card mb-2 text-decoration-none">
            <div className="card-body d-flex align-items-center gap-3">
              {h.photo_path ? (
                <img src={tileSrc(h)} alt="" className="hr-thumb" style={{ width: 56, height: 56 }} />
              ) : (
                <div className="rounded" style={{ width: 56, height: 56, background: 'rgba(0,0,0,0.3)', border: '1px dashed var(--border)' }} />
              )}
              <div>
                <div className="font-mono fw-semibold" style={{ color: 'var(--neon-cyan)' }}>{h.display_id}</div>
                <div className="text-secondary small">
                  {h.style.replace(/_/g, ' ')} {h.is_beanie ? '(beanie)' : ''}
                </div>
              </div>
            </div>
          </Link>
        ))
      )}

      <div className="card mt-4">
        <div className="card-body">
          <div className="card-title">Tag this case</div>
          <p className="text-secondary small">
            Write this to an NFC sticker on the case, or print QR labels for
            every hat inside it.
          </p>
          <TagUrlRow kind="c" ident={data.display_id} />
          <a
            href={`/api/admin/hat-labels?case=${encodeURIComponent(data.display_id)}`}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-outline-secondary btn-sm mt-2"
          >🏷 Print labels for these hats</a>
        </div>
      </div>

      <button
        className="btn btn-danger w-100 mt-4"
        onClick={() => {
          const msg = data.hat_count > 0
            ? `Delete this case? Its ${data.hat_count} hat(s) will become unassigned.`
            : 'Delete this empty case?';
          if (confirm(msg)) removeMutation.mutate();
        }}
      >
        Delete Case
      </button>
    </>
  );
}
