import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate, Link } from 'react-router';
import { getHat, deleteHat, uploadHatPhoto, reanalyzeHat, recutHat, refreshEbayForHat, undisposeHat, updateHatColors, logWear, undoLatestWear } from '../api/hats';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ConditionBadge } from '../components/common/ConditionBadge';
import { ImageLightbox } from '../components/common/ImageLightbox';
import { PhotoCapture } from '../components/photos/PhotoCapture';
import { DisposeModal } from '../components/common/DisposeModal';
import { ColorEditModal } from '../components/common/ColorEditModal';
import { AnalysisStatus } from '../components/hats/AnalysisStatus';
import { HatNotesCard } from '../components/hats/HatNotesCard';
import { TagUrlRow } from '../components/common/TagUrlRow';
import { useState } from 'react';
import { invalidateHatViews } from '../lib/invalidate';
import { money, valueHat } from '../lib/valuation';
import type { HatRead } from '../types';

/**
 * Hover text for the constructions worth explaining. Anything not listed —
 * every specialty fabric — gets a plain "<name> construction", which is all
 * there is to say about a material whose name already says it.
 */
const CONSTRUCTION_TITLES: Record<string, string> = {
  HYDROLite: 'melin HYDROLite: featherweight, bonded seams, gel-welded logo, antimicrobial sweatband',
  HYDRO: 'melin HYDRO water-resistant construction',
};

/**
 * The hat's ID heading, with the case part of it linking to that case.
 *
 * `A-029-01` reads as "hat 01 of case A-029" and people tap the case part
 * expecting to land there — it looks like a breadcrumb because it is one. The
 * "View Case" button further down the page did already exist, but it is below
 * the identification card, the photo and the specs, which is a lot of
 * scrolling to get back to where you came from.
 *
 * The suffix is sliced off `display_id` rather than rebuilt from
 * `position_in_case`, so the server stays the only place that decides how an
 * ID is formatted. Padding the number here would be a second copy of that
 * rule, free to drift.
 */
export function HatHeadingId({ hat }: { hat: HatRead }) {
  const caseId = hat.case_display_id;
  // An unassigned hat has no display_id at all — nothing to link to, and
  // `Hat #12` must not be dressed up as navigation.
  if (!caseId || !hat.display_id?.startsWith(caseId)) {
    return <>{hat.display_id || `Hat #${hat.id}`}</>;
  }
  return (
    <>
      <Link
        to={`/cases/${caseId}`}
        style={{ color: 'inherit', textDecoration: 'underline', textUnderlineOffset: '0.2em' }}
        title={`Back to case ${caseId}`}
      >
        {caseId}
      </Link>
      {hat.display_id.slice(caseId.length)}
    </>
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
    // Analysis runs on a background worker now, so the result arrives after
    // this page has already rendered. Poll while it's pending and stop the
    // moment it reaches any terminal status — returning false is what ends the
    // polling, so a hat that errors or is skipped doesn't get hammered forever.
    refetchInterval: query =>
      query.state.data?.analysis_status === 'pending' ? 2000 : false,
  });

  const removeMutation = useMutation({
    mutationFn: () => deleteHat(id),
    onSuccess: () => {
      invalidateHatViews(qc, id);
      navigate('/hats');
    },
  });

  const recutMut = useMutation({
    mutationFn: () => recutHat(id),
    onSuccess: () => invalidateHatViews(qc, id),
  });

  const reanalyzeMut = useMutation({
    mutationFn: () => reanalyzeHat(id),
    onMutate: () => setReanalyzing(true),
    onSettled: () => setReanalyzing(false),
    onSuccess: () => {
      invalidateHatViews(qc, id);
    },
  });

  // Wipe the whole palette in one call — PUT /colors replaces the set, so an
  // empty list IS the delete-all. Beats removing swatches one modal at a time
  // after a bad analysis.
  const clearColorsMutation = useMutation({
    mutationFn: () => updateHatColors(id, []),
    onSuccess: () => {
      invalidateHatViews(qc, id);
    },
  });

  const wearMut = useMutation({
    mutationFn: () => logWear(id),
    onSuccess: () => invalidateHatViews(qc, id),
  });

  const undoWearMut = useMutation({
    mutationFn: () => undoLatestWear(id),
    onSuccess: () => invalidateHatViews(qc, id),
  });

  async function handlePhotoUpload(file: File) {
    setUploading(true);
    try {
      await uploadHatPhoto(id, file);
      invalidateHatViews(qc, id);
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
  // Plain call, not a hook — it's pure and cheap, and putting it here keeps it
  // below the `!data` guard without needing a null-safe variant.
  const hatValue = valueHat(data);

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3 gap-2 flex-wrap">
        <h1 className="font-mono" style={{ color: 'var(--neon-cyan)' }}>
          <HatHeadingId hat={data} />
        </h1>
        {/* `flex-wrap` so the row breaks onto a second line instead of
            overflowing the viewport on a phone — this is the row that a
            long badge used to push out of shape. */}
        <div className="d-flex gap-2 align-items-center flex-wrap">
          {/* Renders whatever the construction says, rather than one badge per
              known flag. A hat in a specialty fabric used to show no badge at
              all: the two booleans could only describe HYDRO and HYDROLite. */}
          {data.construction && (
            <span className="badge bg-info" title={CONSTRUCTION_TITLES[data.construction] || `${data.construction} construction`}>
              {data.construction}
            </span>
          )}
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
                {data.artist_series && (
                  <div
                    className="font-mono small"
                    style={{ marginTop: 6, color: 'var(--neon-cyan)' }}
                    title="Signature collaboration / artist series"
                  >
                    ✦ {data.artist_series}
                  </div>
                )}
                {data.logo_detected && (
                  <div
                    className="text-secondary small"
                    style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 6 }}
                    title="A mark was actually visible in the photo — this is evidence, not an inference from shape or colourway"
                  >
                    <span aria-hidden="true">◉</span>
                    <span>Logo: {data.logo_detected}</span>
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

      <HatNotesCard hat={data} />

      <div className="card mb-3">
        <div className="card-body">
          {data.photo_path ? (
            <>
              <ImageLightbox src={`/uploads/${data.photo_path}`} alt={data.display_id || 'Hat photo'} hat />
              <div className="mt-3 d-flex gap-2 flex-wrap">
                <PhotoCapture onCapture={handlePhotoUpload} hidePreview />
                {/* Up here with the other primary actions, not only at the foot
                    of the page. Correcting a misidentification is the most
                    common thing you do right after reading one, and the copy of
                    this button below sits under the colours and disposition
                    sections — on a phone that is most of a screen of scrolling
                    away from the wrong answer you are looking at. */}
                <Link
                  to={`/hats/${data.id}/edit`}
                  className="btn btn-outline-secondary"
                  title="Correct the brand, model, construction, collection or colours"
                >
                  ✎ Edit
                </Link>
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
                {/* Only offered when there is an original to cut from. Hats
                    analysed before originals were retained have none, and the
                    stored cutout can never be re-segmented — doing so eats the
                    alpha and trims the bill a little more each pass. */}
                {data.original_path && (
                  <button
                    type="button"
                    className="btn btn-outline-secondary"
                    onClick={() => recutMut.mutate()}
                    disabled={recutMut.isPending || data.analysis_status === 'pending'}
                    title="Redo the background removal from the original photo"
                  >
                    {recutMut.isPending ? '✂ Re-cutting…' : '✂ Redo cutout'}
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
                {/* Cost per wear needs what was PAID. It used to fall back to
                    the estimated retail price, which answers a different
                    question — a hat bought half-price showed a cost per wear
                    it never had, on the one figure meant to reflect a real
                    decision. Absent a purchase price, the honest output is
                    nothing. */}
                {data.wear_count > 0 && data.purchase_price != null && (
                  <span>
                    ${(data.purchase_price / data.wear_count).toFixed(2)}/wear
                  </span>
                )}
                {data.wear_count > 0 && (
                  <button type="button" className="btn btn-link btn-sm p-0" style={{ fontSize: 'inherit' }}
                    onClick={() => undoWearMut.mutate()}>undo</button>
                )}
              </div>
              {recutMut.error && (
                <div className="alert alert-danger mt-2 mb-0">{String(recutMut.error)}</div>
              )}
              {reanalyzeMut.error && (
                <div className="alert alert-danger mt-2 mb-0">{String(reanalyzeMut.error)}</div>
              )}
            </>
          ) : (
            <PhotoCapture onCapture={handlePhotoUpload} previewUrl={null} />
          )}
          {uploading && (
            <div className="text-secondary small mt-2 font-mono" style={{ letterSpacing: '0.08em' }}>
              {/* Since 2.6.0 the POST only saves the photo and queues the
                  rest, so claiming to remove backgrounds and call Claude here
                  is a description of what the *worker* does afterwards. The
                  Analyzing… badge covers that part. */}
              ↑ Uploading photo…
            </div>
          )}
        </div>
      </div>

      {/* Pricing */}
      {(data.estimated_new_price !== null || data.purchase_price !== null
        || data.resale_price_url || data.ebay_search_url) && (
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
            {/* Two-up rather than three-across: at 375px the old row gave each
                tile ~110px, which a four-digit price and a source line don't
                fit into. */}
            <div className="row g-2">
              <div className="col-6">
                <PriceTile
                  label="New Retail"
                  value={data.estimated_new_price ?? null}
                  source={data.estimated_new_price_source}
                />
              </div>
              <div className="col-6">
                <PriceTile
                  label="Paid"
                  value={data.purchase_price ?? null}
                  source={data.purchased_at
                    ? new Date(data.purchased_at).toLocaleDateString()
                    : 'not recorded'}
                />
              </div>
              <div className="col-6">
                <PriceTile
                  label="eBay ask"
                  value={data.ebay_median_price ?? null}
                  source={data.ebay_listing_count != null
                    ? `median of ${data.ebay_listing_count} live listings`
                    : 'configure eBay key'}
                />
              </div>
              <div className="col-6">
                {/* Was labelled "Resale (manual)" while holding a scraped
                    median for all but the rare hand-entered price — the label
                    named the exception. */}
                <PriceTile
                  label="Resale ask"
                  value={data.resale_price ?? null}
                  source={data.resale_price_source}
                />
              </div>
            </div>
            {/* The figure the collection totals actually use, shown next to
                the raw inputs so the two can be reconciled on one screen. */}
            <div className="hr-metric mt-2">
              <div className="hr-metric-label">Est. sale value</div>
              <div className="hr-metric-value hr-price hr-price-large">
                {hatValue.value != null ? money(hatValue.value) : '—'}
              </div>
              <div className="text-muted mt-1" style={{ fontSize: '0.7rem', lineHeight: 1.45 }}>
                {hatValue.explanation}
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
                  invalidateHatViews(qc, id);
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
          {/* "Type" used to sit here showing Beanie or Regular — which is
              derived entirely from Style directly above it (`is_beanie` is
              set from the style on every write), so the sheet spent a quarter
              of itself printing one fact twice.

              Construction and colourway are what actually separate two hats
              of the same style, and neither was here: construction appeared
              only as a badge by the title, and colourway appeared nowhere on
              this page at all, despite a catalog and a purchase matcher whose
              whole job is filling it in. */}
          <div className="row g-2">
            {([
              ['Style', data.style.replace(/_/g, ' ')],
              ['Size', data.size.replace(/_/g, ' ')],
              ['Construction', data.construction],
              ['Colorway', data.colorway],
              ['Collection', data.artist_series],
              ['Last Worn', data.date_last_worn],
            ] as const).map(([label, value]) => (
              <div className="col-6" key={label}>
                <div className="hr-metric">
                  <div className="hr-metric-label">{label}</div>
                  <div
                    className="hr-metric-value"
                    style={{ fontSize: '0.95rem', overflowWrap: 'anywhere' }}
                  >
                    {value || '—'}
                  </div>
                </div>
              </div>
            ))}
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
            <div className="d-flex gap-2">
              {data.colors.length > 0 && (
                <button
                  type="button"
                  className="btn btn-outline-danger btn-sm"
                  onClick={() => {
                    if (confirm(`Remove all ${data.colors.length} colors from this hat?`)) {
                      clearColorsMutation.mutate();
                    }
                  }}
                  disabled={clearColorsMutation.isPending}
                >
                  {clearColorsMutation.isPending ? 'Clearing…' : 'Clear All'}
                </button>
              )}
              <button
                type="button"
                className="btn btn-outline-primary btn-sm"
                onClick={() => setColorEditOpen(-1)}
              >
                + Add Color
              </button>
            </div>
          </div>
          {clearColorsMutation.error && (
            <div className="alert alert-danger small">{String(clearColorsMutation.error)}</div>
          )}
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

      {/* Physical tag. Sits on the hat's own page because that is where you
          are standing when you tag it — holding this hat, with a blank NFC
          sticker and a tag writer open. */}
      <div className="card mb-3">
        <div className="card-body">
          <div className="card-title">Tag this hat</div>
          <p className="text-secondary small">
            Write this to an NFC sticker, or print a QR from{' '}
            <Link to="/settings">Settings</Link>. Scanning it opens a one-tap
            “wore it today” screen.
          </p>
          <TagUrlRow kind="h" ident={data.id} />
        </div>
      </div>

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
