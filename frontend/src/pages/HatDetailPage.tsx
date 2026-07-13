import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { getHat, deleteHat, uploadHatPhoto, reanalyzeHat, refreshEbayForHat, undisposeHat } from '../api/hats';
import { apiFetch } from '../api/client';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ConditionBadge } from '../components/common/ConditionBadge';
import { ImageLightbox } from '../components/common/ImageLightbox';
import { PhotoCapture } from '../components/photos/PhotoCapture';
import { DisposeModal } from '../components/common/DisposeModal';
import { ColorEditModal } from '../components/common/ColorEditModal';
import type { HatRead } from '../types';
import { useState } from 'react';

function AnalysisStatus({ hat }: { hat: HatRead }) {
  if (!hat.analysis_status) return null;
  const status = hat.analysis_status;
  const label =
    status === 'ok' ? 'Analyzed'
    : status === 'skipped' ? 'No API key'
    : status === 'fallback' ? 'Basic ID (fallback)'
    : 'Analysis failed';
  return (
    <span className={`hr-analysis-status ${status}`} title={hat.analysis_error || undefined}>
      <span className="dot" />
      {label}
    </span>
  );
}

function PriceTile({ label, value, source }: { label: string; value: number | null; source?: string | null }) {
  return (
    <div className="hr-metric">
      <div className="hr-metric-label">{label}</div>
      {value !== null && value !== undefined ? (
        <>
          <div className="hr-metric-value hr-price">${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
          {source && <div className="text-muted" style={{ fontSize: '0.65rem', marginTop: 2 }}>{source}</div>}
        </>
      ) : (
        <div className="hr-metric-value text-muted" style={{ fontSize: '0.95rem' }}>—</div>
      )}
    </div>
  );
}

export function HatDetailPage() {
  const { hatId } = useParams<{ hatId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [uploading, setUploading] = useState(false);
  const [reanalyzing, setReanalyzing] = useState(false);
  const [disposeOpen, setDisposeOpen] = useState(false);
  const [refreshingEbay, setRefreshingEbay] = useState(false);
  // null = closed, -1 = adding, >= 1 = editing that dominance_rank
  const [colorEditOpen, setColorEditOpen] = useState<number | null>(null);

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

  const reanalyzeMut = useMutation({
    mutationFn: () => reanalyzeHat(id),
    onMutate: () => setReanalyzing(true),
    onSettled: () => setReanalyzing(false),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['hat', id] });
      qc.invalidateQueries({ queryKey: ['hats'] });
    },
  });

  const wearMut = useMutation({
    mutationFn: () => apiFetch(`/api/hats/${id}/wear`, { method: 'POST', body: JSON.stringify({}) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['hat', id] }),
  });

  const undoWearMut = useMutation({
    mutationFn: () => apiFetch(`/api/hats/${id}/wear/latest`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['hat', id] }),
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
  if (error || !data) return (
    <div className="text-center py-5">
      <h5 className="mb-2">Hat not found</h5>
      <p className="text-secondary small mb-3">This hat may have been deleted or doesn't exist.</p>
      <Link to="/hats" className="btn btn-outline-primary">← Back to Hats</Link>
    </div>
  );

  const caseTypeLabel = data.case_type === 'archive' ? 'Archive' : data.case_type === 'daily_wear' ? 'Daily Wear' : null;

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3 gap-2 flex-wrap">
        <h1 className="font-mono" style={{ color: 'var(--neon-cyan)' }}>
          {data.display_id || `Hat #${data.id}`}
        </h1>
        <div className="d-flex gap-2 align-items-center">
          <AnalysisStatus hat={data} />
          <ConditionBadge condition={data.condition} />
        </div>
      </div>

      {data.brand && (
        <div className="card hr-feature mb-3">
          <div className="card-body">
            <div className="card-title">Identification</div>
            <div className="d-flex justify-content-between align-items-start gap-2 flex-wrap">
              <div>
                <div className="font-display" style={{ fontSize: '1.5rem', color: 'var(--neon-pink)', letterSpacing: '0.04em' }}>
                  {data.brand}
                </div>
                {data.model_name && (
                  <div className="font-mono fs-5" style={{ color: 'var(--text)', marginTop: 2 }}>
                    {data.model_name}
                  </div>
                )}
                {data.style_descriptor && (
                  <div className="text-secondary small" style={{ marginTop: 4 }}>
                    {data.style_descriptor}
                  </div>
                )}
              </div>
              {data.model_confidence && (
                <span className={`badge ${data.model_confidence === 'high' ? 'bg-info' : data.model_confidence === 'medium' ? 'bg-warning' : 'bg-secondary'}`}>
                  {data.model_confidence} conf
                </span>
              )}
            </div>
            {data.design_notes && (
              <p className="text-secondary mt-3 mb-0" style={{ fontStyle: 'italic', lineHeight: 1.5 }}>
                "{data.design_notes}"
              </p>
            )}
          </div>
        </div>
      )}

      <div className="card mb-3">
        <div className="card-body">
          {data.photo_path ? (
            <>
              <ImageLightbox src={`/uploads/${data.photo_path}`} alt={data.display_id || 'Hat photo'} hat />
              <div className="mt-3 d-flex gap-2 flex-wrap">
                <PhotoCapture onCapture={handlePhotoUpload} hidePreview />
                {data.photo_path && (
                  <button
                    type="button"
                    className="btn btn-outline-secondary"
                    onClick={() => reanalyzeMut.mutate()}
                    disabled={reanalyzing}
                    title="Re-run analysis (Claude, or the fallback when no key is set)"
                  >
                    {reanalyzing ? '↻ Analyzing…' : '↻ Reanalyze'}
                  </button>
                )}
                {!data.disposed_at && (
                  <button
                    type="button"
                    className="btn btn-outline-primary"
                    onClick={() => wearMut.mutate()}
                    disabled={wearMut.isPending}
                    title="Log a wear for today"
                  >
                    🧢 Wearing this today
                  </button>
                )}
              </div>
              <div className="text-secondary small mt-2 d-flex gap-3 flex-wrap">
                <span>Worn <strong>{data.wear_count}×</strong></span>
                {data.date_last_worn && <span>last: {data.date_last_worn}</span>}
                {data.wear_count > 0 && (data.purchase_price ?? data.estimated_new_price) != null && (
                  <span>
                    ${(((data.purchase_price ?? data.estimated_new_price) as number) / data.wear_count).toFixed(2)}/wear
                  </span>
                )}
                {data.wear_count > 0 && (
                  <button type="button" className="btn btn-link btn-sm p-0" style={{ fontSize: 'inherit' }}
                    onClick={() => undoWearMut.mutate()}>undo</button>
                )}
              </div>
              {reanalyzeMut.error && (
                <div className="alert alert-danger mt-2 mb-0">{String(reanalyzeMut.error)}</div>
              )}
            </>
          ) : (
            <PhotoCapture onCapture={handlePhotoUpload} previewUrl={null} />
          )}
          {uploading && (
            <div className="text-secondary small mt-2 font-mono" style={{ letterSpacing: '0.08em' }}>
              ↑ Uploading · removing background · analyzing with Claude…
            </div>
          )}
        </div>
      </div>

      {/* Pricing */}
      {(data.estimated_new_price !== null || data.resale_price_url || data.ebay_search_url) && (
        <div className="card mb-3">
          <div className="card-body">
            <div className="d-flex justify-content-between align-items-center mb-2">
              <div className="card-title mb-0">Valuation</div>
              {data.brand && data.model_name && (
                <button
                  type="button"
                  className="btn btn-outline-secondary btn-sm"
                  onClick={async () => {
                    setRefreshingEbay(true);
                    try {
                      await refreshEbayForHat(id);
                      qc.invalidateQueries({ queryKey: ['hat', id] });
                    } finally { setRefreshingEbay(false); }
                  }}
                  disabled={refreshingEbay}
                  title="Refresh eBay comparable-listings prices"
                >
                  {refreshingEbay ? '↻ eBay…' : '↻ eBay'}
                </button>
              )}
            </div>
            <div className="row g-2">
              <div className="col-4">
                <PriceTile
                  label="New Retail"
                  value={data.estimated_new_price ?? null}
                  source={data.estimated_new_price_source}
                />
              </div>
              <div className="col-4">
                <PriceTile
                  label="eBay Median"
                  value={data.ebay_median_price ?? null}
                  source={data.ebay_listing_count != null
                    ? `${data.ebay_listing_count} listings`
                    : 'configure eBay key'}
                />
              </div>
              <div className="col-4">
                <PriceTile
                  label="Resale (manual)"
                  value={data.resale_price ?? null}
                  source={data.resale_price_source}
                />
              </div>
            </div>
            <div className="d-flex gap-2 flex-wrap mt-3">
              {data.ebay_search_url && (
                <a
                  href={data.ebay_search_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn btn-outline-primary btn-sm flex-fill"
                >
                  Browse eBay →
                </a>
              )}
              {data.resale_price_url && (
                <a
                  href={data.resale_price_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn btn-outline-primary btn-sm flex-fill"
                >
                  Browse {data.resale_price_source || 'Resale'} →
                </a>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Disposition */}
      <div className="card mb-3">
        <div className="card-body">
          <div className="card-title">Disposition</div>
          {data.disposed_at ? (
            <>
              <div className="hr-metric mb-2">
                <div className="hr-metric-label">{data.disposed_via?.toUpperCase()} on {new Date(data.disposed_at).toLocaleDateString()}</div>
                {data.disposed_price != null && (
                  <div className="hr-metric-value hr-price">
                    ${data.disposed_price.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </div>
                )}
                {data.disposed_to && (
                  <div className="text-secondary small" style={{ marginTop: 4 }}>
                    {data.disposed_to}
                  </div>
                )}
                {data.disposed_notes && (
                  <div className="text-muted small" style={{ marginTop: 4, fontStyle: 'italic' }}>
                    "{data.disposed_notes}"
                  </div>
                )}
              </div>
              <button
                type="button"
                className="btn btn-outline-secondary btn-sm"
                onClick={async () => {
                  if (!confirm('Restore this hat to active inventory?')) return;
                  await undisposeHat(id);
                  qc.invalidateQueries({ queryKey: ['hat', id] });
                  qc.invalidateQueries({ queryKey: ['hats'] });
                }}
              >
                Undo — restore to active
              </button>
            </>
          ) : (
            <>
              <p className="text-secondary small mb-2">
                Mark this hat as sold, gifted, traded, lost, or trashed. Soft-delete only — undoable.
              </p>
              <button
                type="button"
                className="btn btn-outline-primary btn-sm"
                onClick={() => setDisposeOpen(true)}
              >
                Mark as Disposed
              </button>
            </>
          )}
        </div>
      </div>

      {/* Specs */}
      <div className="card mb-3">
        <div className="card-body">
          <div className="card-title">Specs</div>
          <div className="row g-2">
            <div className="col-6"><div className="hr-metric"><div className="hr-metric-label">Style</div><div className="hr-metric-value">{data.style.replace(/_/g, ' ')}</div></div></div>
            <div className="col-6"><div className="hr-metric"><div className="hr-metric-label">Size</div><div className="hr-metric-value">{data.size.replace(/_/g, ' ')}</div></div></div>
            <div className="col-6"><div className="hr-metric"><div className="hr-metric-label">Last Worn</div><div className="hr-metric-value" style={{ fontSize: '0.95rem' }}>{data.date_last_worn || '—'}</div></div></div>
            <div className="col-6"><div className="hr-metric"><div className="hr-metric-label">Type</div><div className="hr-metric-value" style={{ fontSize: '0.95rem' }}>{data.is_beanie ? 'Beanie' : 'Regular'}</div></div></div>
          </div>
        </div>
      </div>

      {/* Case info */}
      <div className={`card mb-3 ${!data.case_display_id ? 'border-warning' : ''}`}>
        <div className="card-body">
          <div className="card-title">Case</div>
          {data.case_display_id ? (
            <div className="d-flex justify-content-between align-items-center gap-2 flex-wrap">
              <div className="d-flex align-items-center gap-2 flex-wrap">
                <span className="font-mono fs-5" style={{ color: 'var(--neon-cyan)' }}>{data.case_display_id}</span>
                {caseTypeLabel && (
                  <span className={`badge ${data.case_type === 'archive' ? 'bg-secondary' : 'bg-info'}`}>
                    {caseTypeLabel}
                  </span>
                )}
                {data.room_name && (
                  <span className="badge bg-info">{data.room_name}</span>
                )}
              </div>
              <Link to={`/cases/${data.case_display_id}`} className="btn btn-outline-primary btn-sm">View Case</Link>
            </div>
          ) : (
            <div className="d-flex justify-content-between align-items-center gap-2 flex-wrap">
              <div style={{ color: 'var(--neon-yellow)' }}>Not assigned to a case</div>
              <Link to={`/hats/${data.id}/edit`} className="btn btn-outline-warning btn-sm">Assign</Link>
            </div>
          )}
        </div>
      </div>

      {/* Colors — tap any row to edit */}
      <div className="card mb-3">
        <div className="card-body">
          <div className="d-flex justify-content-between align-items-center mb-2">
            <div className="card-title mb-0">Color Palette</div>
            <button
              type="button"
              className="btn btn-outline-primary btn-sm"
              onClick={() => setColorEditOpen(-1)}
            >
              + Add Color
            </button>
          </div>
          {data.colors.length === 0 ? (
            <p className="text-muted small mb-0">
              No colors yet — tap "Add Color" to seed the palette manually, or run Reanalyze.
            </p>
          ) : (
            data.colors.map(c => (
              <button
                key={c.dominance_rank}
                type="button"
                className="hr-color-row"
                onClick={() => setColorEditOpen(c.dominance_rank)}
                style={{
                  width: '100%', background: 'transparent', border: 0,
                  textAlign: 'left', cursor: 'pointer',
                }}
                title="Tap to edit"
              >
                <div
                  className="color-swatch"
                  style={{ width: 32, height: 32, backgroundColor: c.hex_value, color: c.hex_value }}
                />
                <div className="flex-grow-1">
                  <div className="fw-semibold">{c.general_color || c.color_name}</div>
                  {c.color_name && c.color_name !== c.general_color && (
                    <div className="text-muted small font-mono">{c.color_name}</div>
                  )}
                </div>
                <div className="text-end">
                  <div className="hr-tier-label">{c.tier || 'primary'}</div>
                  <div className="text-muted font-mono small">{c.hex_value}</div>
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {data.analysis_status === 'skipped' && (
        <div className="alert alert-info mb-3">
          Configure your Anthropic API key in <Link to="/settings" style={{ color: 'inherit', textDecoration: 'underline' }}>Settings</Link> to enable AI brand/color/price detection.
        </div>
      )}

      {data.analysis_status === 'fallback' && (
        <div className="alert alert-info mb-3 small">
          Basic fallback ID only (colors from the photo cutout{data.brand ? ', brand from logo detection' : ''}).
          Add a Claude API key in <Link to="/settings" style={{ color: 'inherit', textDecoration: 'underline' }}>Settings</Link> and
          hit Reanalyze for full model + price identification.
        </div>
      )}

      {data.analysis_status === 'error' && data.analysis_error && (
        <div className="alert alert-danger mb-3 small">
          Analysis error: {data.analysis_error}
        </div>
      )}

      <Link to="/hats/new" className="btn btn-primary w-100 mb-2">+ Add Another Hat</Link>

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

      <DisposeModal hatId={data.id} show={disposeOpen} onClose={() => setDisposeOpen(false)} />
      {colorEditOpen !== null && (
        <ColorEditModal
          hatId={data.id}
          colors={data.colors}
          editingRank={colorEditOpen >= 0 ? colorEditOpen : null}
          onClose={() => setColorEditOpen(null)}
        />
      )}
    </>
  );
}
