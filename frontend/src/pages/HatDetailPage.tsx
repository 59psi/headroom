import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { getHat, deleteHat, uploadHatPhoto } from '../api/hats';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ConditionBadge } from '../components/common/ConditionBadge';
import { ImageLightbox } from '../components/common/ImageLightbox';
import { PhotoCapture } from '../components/photos/PhotoCapture';
import { useState } from 'react';

export function HatDetailPage() {
  const { hatId } = useParams<{ hatId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [uploading, setUploading] = useState(false);

  const id = Number(hatId);
  const { data, isLoading, error } = useQuery({
    queryKey: ['hat', id],
    queryFn: () => getHat(id),
    enabled: !isNaN(id),
  });

  const removeMutation = useMutation({
    mutationFn: () => deleteHat(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['hats'] });
      navigate('/hats');
    },
  });

  async function handlePhotoUpload(file: File) {
    setUploading(true);
    try {
      await uploadHatPhoto(id, file);
      qc.invalidateQueries({ queryKey: ['hat', id] });
      qc.invalidateQueries({ queryKey: ['hats'] });
    } finally {
      setUploading(false);
    }
  }

  if (isLoading) return <LoadingSpinner />;
  if (error || !data) return <div className="alert alert-danger">Hat not found</div>;

  const caseTypeLabel = data.case_type === 'archive' ? 'Archive' : data.case_type === 'daily_wear' ? 'Daily Wear' : null;

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h1>{data.display_id || `Hat #${data.id}`}</h1>
        <ConditionBadge condition={data.condition} />
      </div>

      <div className="card mb-3">
        <div className="card-body">
          {data.photo_path ? (
            <>
              <ImageLightbox src={`/uploads/${data.photo_path}`} alt={data.display_id || 'Hat photo'} />
              <div className="mt-2">
                <PhotoCapture onCapture={handlePhotoUpload} hidePreview />
              </div>
            </>
          ) : (
            <PhotoCapture onCapture={handlePhotoUpload} previewUrl={null} />
          )}
          {uploading && <div className="text-secondary small">Uploading & detecting colors...</div>}
        </div>
      </div>

      <div className="card mb-3">
        <div className="card-body">
          <div className="row">
            <div className="col-6 mb-3">
              <div className="text-secondary small">Style</div>
              <div className="fw-semibold">{data.style.replace(/_/g, ' ')}</div>
            </div>
            <div className="col-6 mb-3">
              <div className="text-secondary small">Size</div>
              <div className="fw-semibold">{data.size.replace(/_/g, ' ')}</div>
            </div>
            <div className="col-6">
              <div className="text-secondary small">Last Worn</div>
              <div className="fw-semibold">{data.date_last_worn || '\u2014'}</div>
            </div>
          </div>
        </div>
      </div>

      {/* Prominent case info */}
      <div className={`card mb-3 ${!data.case_display_id ? 'border-warning' : ''}`}>
        <div className="card-body">
          <div className="text-secondary small mb-1">Case</div>
          {data.case_display_id ? (
            <div className="d-flex justify-content-between align-items-center">
              <div>
                <span className="fw-semibold fs-5">Stored in: {data.case_display_id}</span>
                {caseTypeLabel && (
                  <span className={`badge ms-2 ${data.case_type === 'archive' ? 'bg-secondary' : 'bg-info'}`}>
                    {caseTypeLabel}
                  </span>
                )}
              </div>
              <Link to={`/cases/${data.case_display_id}`} className="btn btn-outline-primary btn-sm">View Case</Link>
            </div>
          ) : (
            <div className="d-flex justify-content-between align-items-center">
              <div className="text-warning fw-semibold">Not assigned to a case</div>
              <Link to={`/hats/${data.id}/edit`} className="btn btn-outline-warning btn-sm">Assign</Link>
            </div>
          )}
        </div>
      </div>

      {data.colors.length > 0 && (
        <div className="card mb-3">
          <div className="card-body">
            <div className="text-secondary small mb-2">Detected Colors</div>
            <div className="d-flex gap-2 flex-wrap">
              {data.colors.map(c => (
                <div key={c.dominance_rank} className="d-flex align-items-center gap-2">
                  <div className="color-swatch" style={{ backgroundColor: c.hex_value, width: 24, height: 24 }} />
                  <span className="small">{c.color_name}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="d-flex gap-2">
        <Link to={`/hats/${data.id}/edit`} className="btn btn-outline-secondary flex-fill">Edit</Link>
        <button
          className="btn btn-danger flex-fill"
          onClick={() => {
            if (confirm('Delete this hat?')) removeMutation.mutate();
          }}
        >
          Delete
        </button>
      </div>
    </>
  );
}
