import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { getCase, deleteCase, uploadCasePhoto } from '../api/cases';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { PhotoCapture } from '../components/photos/PhotoCapture';
import { useState } from 'react';

export function CaseDetailPage() {
  const { displayId } = useParams<{ displayId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [uploading, setUploading] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ['case', displayId],
    queryFn: () => getCase(displayId!),
    enabled: !!displayId,
  });

  const removeMutation = useMutation({
    mutationFn: () => deleteCase(displayId!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cases'] });
      navigate('/cases');
    },
  });

  async function handlePhotoUpload(file: File) {
    setUploading(true);
    try {
      await uploadCasePhoto(displayId!, file);
      qc.invalidateQueries({ queryKey: ['case', displayId] });
      qc.invalidateQueries({ queryKey: ['cases'] });
    } finally {
      setUploading(false);
    }
  }

  if (isLoading) return <LoadingSpinner />;
  if (error || !data) return <div className="alert alert-danger">Case not found</div>;

  const typeLabel = data.case_type === 'archive' ? 'Archive' : 'Daily Wear';

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h1>{data.display_id}</h1>
        <div className="d-flex gap-2 align-items-center">
          <span className="badge bg-secondary">{typeLabel}</span>
          <Link to={`/cases/${displayId}/edit`} className="btn btn-outline-secondary btn-sm">Edit</Link>
        </div>
      </div>

      <div className="card mb-3">
        <div className="card-body">
          <PhotoCapture
            onCapture={handlePhotoUpload}
            previewUrl={data.photo_path ? `/uploads/${data.photo_path}` : null}
          />
          {uploading && <div className="text-secondary small">Uploading...</div>}

          <div className="row text-center mt-3">
            <div className="col-4">
              <div className="fs-4 fw-bold">{data.hat_count}</div>
              <div className="text-secondary small">Total</div>
            </div>
            <div className="col-4">
              <div className="fs-4 fw-bold">{data.regular_count}/4</div>
              <div className="text-secondary small">Regular</div>
            </div>
            <div className="col-4">
              <div className="fs-4 fw-bold">{data.beanie_count}/6</div>
              <div className="text-secondary small">Beanies</div>
            </div>
          </div>
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
          <Link key={h.id} to={`/hats/${h.id}`} className="card mb-2 text-decoration-none text-body">
            <div className="card-body d-flex align-items-center gap-3">
              {h.photo_path ? (
                <img src={`/uploads/${h.photo_path}`} alt="" className="rounded" style={{ width: 56, height: 56, objectFit: 'cover' }} />
              ) : (
                <div className="rounded" style={{ width: 56, height: 56, background: 'var(--color-border)' }} />
              )}
              <div>
                <div className="fw-semibold">{h.display_id}</div>
                <div className="text-secondary small">
                  {h.style.replace(/_/g, ' ')} {h.is_beanie ? '(beanie)' : ''}
                </div>
              </div>
            </div>
          </Link>
        ))
      )}

      {data.hat_count === 0 && (
        <button
          className="btn btn-danger w-100 mt-4"
          onClick={() => {
            if (confirm('Delete this empty case?')) removeMutation.mutate();
          }}
        >
          Delete Case
        </button>
      )}
    </>
  );
}
