import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate, Link } from 'react-router';
import { getHat, deleteHat, uploadHatPhoto, reanalyzeHat, recutHat, refreshEbayForHat, undisposeHat, updateHatColors, logWear, undoLatestWear } from '../api/hats';
import { ConditionBadge } from '../components/common/ConditionBadge';
import { ImageLightbox } from '../components/common/ImageLightbox';
import { PhotoCapture } from '../components/photos/PhotoCapture';
import { DisposeModal, dispositionLabel } from '../components/common/DisposeModal';
import { ColorEditModal } from '../components/common/ColorEditModal';
import { AnalysisStatus } from '../components/hats/AnalysisStatus';
import { HatNotesCard } from '../components/hats/HatNotesCard';
import { TagUrlRow } from '../components/common/TagUrlRow';
import { PageHeader } from '../components/ui/PageHeader';
import { Panel } from '../components/ui/Panel';
import { StatusPill } from '../components/ui/StatusPill';
import { Skeleton } from '../components/ui/Skeleton';
import { useToast } from '../components/ui/Toast';
import { useConfirm } from '../components/ui/Dialogs';
import { useHatLabels } from '../lib/labels';
import { useState } from 'react';
import { invalidateHatViews } from '../lib/invalidate';
import { ErrorNote } from '../components/common/ErrorNote';
import { isNotFound } from '../api/client';
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

const CONFIDENCE_TONE = { high: 'info', medium: 'warn', low: 'off' } as const;

/**
 * The hat's ID heading, with the case part of it linking to that case.
 *
 * `A-029-01` reads as "hat 01 of case A-029" and people tap the case part
 * expecting to land there — it looks like a breadcrumb because it is one. The
 * "View case" button further down the page did already exist, but it is below
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
      <Link to={`/cases/${caseId}`} className="hr-crumb-link" title={`Back to case ${caseId}`}>
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
          {source && <div className="hr-metric-source">{source}</div>}
        </>
      ) : (
        <div className="hr-metric-value hr-metric-empty">—</div>
      )}
    </div>
  );
}

/**
 * A write's response, when it is this hat's fresh row.
 *
 * Most writes here answer with the updated `HatRead`. Putting it straight
 * into the cache shows the result now — a new photo's "Analyzing" badge, a
 * restored hat's case — instead of after the invalidation's refetch lands.
 * It is the server's answer, not a guess at one, so nothing needs rolling
 * back. Checked rather than trusted: two API wrappers type their result
 * `unknown`, and a test double may return nothing.
 */
function freshHat(res: unknown, id: number): HatRead | null {
  return res && typeof res === 'object' && (res as { id?: unknown }).id === id ? res as HatRead : null;
}

/** The page's shape while the hat loads: title, photo, then two cards of text. */
function HatDetailSkeleton() {
  return (
    <>
      {/* The title's place is held by the header's own bar (decoration). The
          photo carries the page's one announcement; the rest are shape only. */}
      <PageHeader loading />
      <div className="hr-hat-layout">
        <div className="hr-hat-aside">
          <div className="card hr-panel">
            <div className="card-body"><Skeleton height={300} label="Loading hat…" /></div>
          </div>
        </div>
        <div className="hr-hat-main">
          <div className="card hr-panel">
            <div className="card-body"><Skeleton lines={4} decorative /></div>
          </div>
          <div className="card hr-panel">
            <div className="card-body"><Skeleton lines={3} decorative /></div>
          </div>
        </div>
      </div>
    </>
  );
}

export function HatDetailPage() {
  const { hatId } = useParams<{ hatId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const labels = useHatLabels();
  const [disposeOpen, setDisposeOpen] = useState(false);
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

  /**
   * Show the server's fresh row now, then refresh everywhere else it shows.
   * `hatId` defaults to the page's hat; the wear mutations pass the hat they
   * were started for (see `undoWearMut`).
   */
  function settle(res: unknown, hatId = id) {
    const hat = freshHat(res, hatId);
    if (hat) qc.setQueryData(['hat', hatId], hat);
    return invalidateHatViews(qc, hatId);
  }

  const removeMutation = useMutation({
    mutationFn: () => deleteHat(id),
    onSuccess: () => {
      invalidateHatViews(qc, id);
      toast.success('Hat deleted');
      navigate('/hats');
    },
  });

  const recutMut = useMutation({
    mutationFn: () => recutHat(id),
    onSuccess: res => {
      settle(res);
      toast.info('Redoing the cutout from the original photo');
    },
  });

  const reanalyzeMut = useMutation({
    mutationFn: () => reanalyzeHat(id),
    onSuccess: res => {
      settle(res);
      // With a key the work is queued and the badge takes over; without one
      // the fallback ran inline and this response IS the result.
      toast.info(freshHat(res, id)?.analysis_status === 'pending' ? 'Reanalysis started' : 'Reanalysis finished');
    },
  });

  // Every write on this page goes through `useMutation` and renders `.error`.
  // Five of them used to be bare `await`s in click handlers (this upload, the
  // eBay refresh, undispose, and — in their own cards — passkey removal and
  // share-link revoke): a 413 from the photo cap, a dropped LAN, a 502 from
  // eBay each vanished into an unhandled rejection and the button simply
  // un-pressed itself.
  const uploadMut = useMutation({
    mutationFn: (file: File) => uploadHatPhoto(id, file),
    onSuccess: res => {
      settle(res);
      toast.success('Photo uploaded');
    },
  });
  const ebayMut = useMutation({
    mutationFn: () => refreshEbayForHat(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['hat', id] });
      toast.success('eBay prices refreshed');
    },
  });
  const undisposeMut = useMutation({
    mutationFn: () => undisposeHat(id),
    onSuccess: res => {
      settle(res);
      toast.success('Hat restored to active');
    },
  });

  // Wipe the whole palette in one call — PUT /colors replaces the set, so an
  // empty list IS the delete-all. Beats removing swatches one modal at a time
  // after a bad analysis.
  //
  // Optimistic: the answer to "replace the colors with none" is no colors,
  // so the palette empties the moment you confirm. A failure puts the old
  // palette back and says so under the card's header.
  const clearColorsMutation = useMutation({
    mutationFn: () => updateHatColors(id, []),
    onMutate: async () => {
      // A poll landing mid-flight would repaint the old palette over the
      // optimistic one.
      await qc.cancelQueries({ queryKey: ['hat', id] });
      const previous = qc.getQueryData<HatRead>(['hat', id]);
      if (previous) qc.setQueryData<HatRead>(['hat', id], { ...previous, colors: [] });
      return { previous };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) qc.setQueryData(['hat', id], ctx.previous);
    },
    onSuccess: () => toast.success('Colors cleared'),
    // Not returned: TanStack holds a mutation's error/success state until a
    // returned `onSettled` promise resolves, which would keep "Clearing…" up
    // and the failure unsaid until every list had refetched. The optimistic
    // state already shows the outcome.
    onSettled: () => { void invalidateHatViews(qc, id); },
  });

  // Both wear mutations take the hat as their argument instead of closing
  // over `id`. The "Wear logged" toast lives at the app root and outlives
  // this page — and React Router keeps this component mounted from one hat's
  // page to the next (Back from hat 13 lands on hat 12 with the same
  // instance), where TanStack hands a mutation the LATEST render's options.
  // A closure over `id` therefore undid a wear on whichever hat was on screen
  // when the toast was tapped, not the one it was logged for.
  const undoWearMut = useMutation({
    mutationFn: (hatId: number) => undoLatestWear(hatId),
    onSuccess: (res, hatId) => {
      settle(res, hatId);
      toast.success('Last wear removed');
    },
  });

  const wearMut = useMutation({
    mutationFn: (hatId: number) => logWear(hatId),
    onSuccess: (res, hatId) => {
      // The server logs one wear per hat per (UTC) day and treats a second
      // tap as a no-op, so the count is compared rather than assumed — and
      // only a wear that was actually added offers an Undo, since undoing a
      // no-op would delete the earlier, real entry.
      const before = qc.getQueryData<HatRead>(['hat', hatId])?.wear_count;
      const after = freshHat(res, hatId)?.wear_count;
      settle(res, hatId);
      if (before != null && after != null && after === before) {
        toast.info('Already logged for today');
        return;
      }
      toast.success('Wear logged', {
        action: {
          label: 'Undo',
          // The server's undo is "delete the LATEST wear", not "delete this
          // one". Once this wear is gone — the inline Undo beside the count
          // took it back — the toast's Undo would delete an earlier, real
          // wear, so it only acts while the count is still the one this wear
          // produced. (Either count unknown — the page's cache already
          // dropped, or the response was not a hat row — still undoes:
          // there is nothing to check against.)
          onClick: () => {
            const now = qc.getQueryData<HatRead>(['hat', hatId])?.wear_count;
            if (after === undefined || now === undefined || now === after) undoWearMut.mutate(hatId);
          },
        },
      });
    },
  });

  async function confirmDelete() {
    const ok = await confirm({
      title: 'Delete this hat?',
      body: (
        <p>
          This permanently deletes it. If it was sold, given away or lost,
          mark it disposed instead — that keeps its record, frees its case
          slot, and can be undone.
        </p>
      ),
      confirmLabel: 'Delete hat',
      tone: 'danger',
    });
    if (ok) removeMutation.mutate();
  }

  async function confirmClearColors(count: number) {
    const ok = await confirm({
      title: `Remove all ${count} colors from this hat?`,
      body: 'You can add them back by hand, or reanalyze to rebuild the palette from the photo.',
      confirmLabel: 'Clear colors',
      tone: 'danger',
    });
    if (ok) clearColorsMutation.mutate();
  }

  async function confirmRestore() {
    const ok = await confirm({
      title: 'Restore this hat to active inventory?',
      body: 'It goes back to its case — or to unassigned, if that case has filled up since.',
      confirmLabel: 'Restore',
    });
    if (ok) undisposeMut.mutate();
  }

  if (isLoading) return <HatDetailSkeleton />;
  // Only a 404 is "not found". A locked database or a dead server used to
  // render the same "may have been deleted" copy — the opposite of the truth.
  if (error && !isNotFound(error)) return (
    <div className="py-4">
      <ErrorNote of={{ isError: true, error }} what="Could not load this hat" />
      <Link to="/hats" className="btn btn-outline-secondary mt-3">← Back to hats</Link>
    </div>
  );
  if (!data) return (
    <div className="text-center py-5">
      <h1 className="hr-empty-title">Hat not found</h1>
      <p className="text-secondary small mb-3">This hat may have been deleted or doesn't exist.</p>
      <Link to="/hats" className="btn btn-outline-secondary">← Back to hats</Link>
    </div>
  );

  const caseTypeLabel = data.case_type === 'archive' ? 'Archive' : data.case_type === 'daily_wear' ? 'Daily wear' : null;
  // Plain call, not a hook — it's pure and cheap, and putting it here keeps it
  // below the `!data` guard without needing a null-safe variant.
  const hatValue = valueHat(data);
  const placed = Boolean(data.case_display_id || data.direct_room_id);

  return (
    <>
      {/* The badges are the header's status cluster, which wraps onto its
          own line on a phone instead of overflowing the viewport — this is
          the row that a long badge used to push out of shape. */}
      <PageHeader
        code
        title={<HatHeadingId hat={data} />}
        status={
          <>
            {/* Renders whatever the construction says, rather than one badge
                per known flag. A hat in a specialty fabric used to show no
                badge at all: the two booleans could only describe HYDRO and
                HYDROLite. */}
            {data.construction && (
              <span className="badge bg-info" title={CONSTRUCTION_TITLES[data.construction] || `${data.construction} construction`}>
                {data.construction}
              </span>
            )}
            <AnalysisStatus hat={data} />
            <ConditionBadge condition={data.condition} />
          </>
        }
      />

      {/* Photo first — it is how you know you are on the right hat — then
          what the hat is and what it is worth, then everything else. On a
          wide screen the photo sits beside the rest, and stays in view where
          the screen is tall enough to hold it (see hat-pages.css); on a
          phone it is simply the top of the page. */}
      <div className="hr-hat-layout">
        <div className="hr-hat-aside">
          <section className="card hr-panel hr-hat-hero" aria-label="Photo and quick actions">
            <div className="card-body">
              {data.photo_path ? (
                <ImageLightbox src={`/uploads/${data.photo_path}`} alt={data.display_id || 'Hat photo'} hat />
              ) : (
                <PhotoCapture onCapture={file => uploadMut.mutate(file)} previewUrl={null} />
              )}
              {uploadMut.isPending && (
                <div className="hr-upload-note" role="status">
                  {/* Since 2.6.0 the POST only saves the photo and queues the
                      rest, so claiming to remove backgrounds and call Claude here
                      is a description of what the *worker* does afterwards. The
                      Analyzing… badge covers that part. */}
                  ↑ Uploading photo…
                </div>
              )}
              <ErrorNote of={uploadMut} className="mt-2 mb-0" />

              {/* The day-to-day actions, under the photo where the thumb is.
                  Logging a wear is the app's primary daily action, so it is
                  the one filled button on the page; the rest are quiet. The
                  wear button and Edit used to exist only once a photo did —
                  neither needs one. */}
              <div className="hr-hero-actions">
                {!data.disposed_at && (
                  <button
                    type="button"
                    className="btn btn-primary hr-hero-primary"
                    onClick={() => wearMut.mutate(data.id)}
                    disabled={wearMut.isPending}
                    title="Log a wear for today"
                  >
                    {/* The bottom nav's line-art cap rather than the 🧢 emoji:
                        an emoji renders in whatever color font the device has
                        (or as a tofu box where it has none), the one element
                        on the page the stylesheet could not match. */}
                    {!wearMut.isPending && (
                      <svg className="hr-btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <path d="M12 2C6.5 2 2 6 2 10c0 2 1 4 3 5v3h14v-3c2-1 3-3 3-5 0-4-4.5-8-10-8z" /><path d="M2 15h20" />
                      </svg>
                    )}
                    {wearMut.isPending ? 'Logging…' : 'Wearing this today'}
                  </button>
                )}
                {data.photo_path && (
                  <PhotoCapture onCapture={file => uploadMut.mutate(file)} hidePreview />
                )}
                {/* Up here with the other primary actions, not only at the foot
                    of the page. Correcting a misidentification is the most
                    common thing you do right after reading one, and the copy of
                    this button below sits under the colors and disposition
                    sections — on a phone that is most of a screen of scrolling
                    away from the wrong answer you are looking at. */}
                <Link
                  to={`/hats/${data.id}/edit`}
                  className="btn btn-outline-secondary"
                  title="Correct the brand, model, construction, collection or colors"
                >
                  ✎ Edit
                </Link>
                {data.photo_path && (
                  <button
                    type="button"
                    className="btn btn-outline-secondary"
                    onClick={() => reanalyzeMut.mutate()}
                    disabled={reanalyzeMut.isPending}
                    title="Re-run analysis (Claude, or the fallback when no key is set)"
                  >
                    {reanalyzeMut.isPending ? '↻ Analyzing…' : '↻ Reanalyze'}
                  </button>
                )}
                {/* Only offered when there is an original to cut from. Hats
                    analyzed before originals were retained have none, and the
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
              </div>

              <div className="hr-wear-line">
                <span>Worn <strong>{data.wear_count}×</strong></span>
                {data.date_last_worn && <span>last {data.date_last_worn}</span>}
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
                  <button
                    type="button"
                    className="btn btn-link btn-sm hr-wear-undo"
                    aria-label="Undo the last logged wear"
                    onClick={() => undoWearMut.mutate(data.id)}
                    disabled={undoWearMut.isPending}
                  >
                    Undo
                  </button>
                )}
              </div>
              {/* The app's primary daily action, and until now the one whose
                  failure said nothing: the button un-pressed and the count
                  stayed put. */}
              <ErrorNote of={[wearMut, undoWearMut]} what="Wear not logged" />
              <ErrorNote of={recutMut} className="mt-2 mb-0" />
              <ErrorNote of={reanalyzeMut} className="mt-2 mb-0" />
            </div>
          </section>
        </div>

        <div className="hr-hat-main">
          {/* The analysis banners sit above what the analysis produced, so the
              reason a card is thin is read before the thin card. */}
          {data.analysis_status === 'skipped' && (
            <div className="alert alert-info mb-3">
              Configure your Anthropic API key in <Link to="/settings?tab=analysis" className="hr-alert-link">Settings</Link> to enable AI brand, color and price detection.
            </div>
          )}

          {/* Fallback means "Claude did not answer", which has two very different
              causes, and this banner used to assert the wrong one. It said "add a
              Claude API key" unconditionally — so when the Anthropic account ran
              out of CREDIT, every hat in the collection told its owner to add the
              key that was already there and plainly working. The real reason was
              sitting in `analysis_error` the whole time and only the `error`
              status ever rendered it. Show it here too. */}
          {data.analysis_status === 'fallback' && (
            <div className="alert alert-info mb-3 small">
              Basic fallback ID only (colors from the photo cutout{data.brand ? ', brand from logo detection' : ''}).
              {data.analysis_error ? (
                <>
                  {' '}<strong>Why:</strong> {data.analysis_error}
                </>
              ) : (
                <>
                  {' '}Add a Claude API key in{' '}
                  <Link to="/settings?tab=analysis" className="hr-alert-link">Settings</Link>
                  {' '}and hit Reanalyze for full model + price identification.
                </>
              )}
            </div>
          )}

          {data.analysis_status === 'error' && data.analysis_error && (
            <div className="alert alert-danger mb-3 small">
              Analysis error: {data.analysis_error}
            </div>
          )}

          {data.brand && (
            <Panel
              title="Identification"
              featured
              status={data.model_confidence && (
                <StatusPill
                  tone={CONFIDENCE_TONE[data.model_confidence as keyof typeof CONFIDENCE_TONE] ?? 'off'}
                  title="How sure the analysis is of the model"
                >
                  {data.model_confidence.charAt(0).toUpperCase() + data.model_confidence.slice(1)} confidence
                </StatusPill>
              )}
            >
              <div className="hr-id-brand">{data.brand}</div>
              {data.model_name && <div className="hr-id-model">{data.model_name}</div>}
              {data.style_descriptor && <div className="hr-id-style">{data.style_descriptor}</div>}
              {data.artist_series && (
                <div className="hr-id-series" title="Signature collaboration / artist series">
                  ✦ {data.artist_series}
                </div>
              )}
              {data.logo_detected && (
                <div
                  className="hr-id-logo"
                  title="A mark was actually visible in the photo — this is evidence, not an inference from shape or colorway"
                >
                  <span aria-hidden="true">◉</span>
                  <span>Logo: {data.logo_detected}</span>
                </div>
              )}
              {data.design_notes && (
                <p className="hr-id-notes">“{data.design_notes}”</p>
              )}
            </Panel>
          )}

          {/* Pricing. Shown when ANY figure exists — `resale_price` and the eBay
              median were missing from this gate, so a hat whose only number was
              the resale price the owner had just typed showed no Valuation card
              at all, and the figure the totals use was nowhere on its own page. */}
          {(data.estimated_new_price != null || data.purchase_price != null
            || data.resale_price != null || data.ebay_median_price != null
            || data.resale_price_url || data.ebay_search_url) && (
            <Panel
              title="Valuation"
              actions={data.brand && data.model_name && (
                <button
                  type="button"
                  className="btn btn-outline-secondary btn-sm"
                  onClick={() => ebayMut.mutate()}
                  disabled={ebayMut.isPending}
                  title="Refresh eBay comparable-listings prices"
                >
                  {ebayMut.isPending ? '↻ Refreshing…' : '↻ Refresh eBay'}
                </button>
              )}
              footer={(data.ebay_search_url || data.resale_price_url) && (
                <>
                  {data.ebay_search_url && (
                    <a
                      href={data.ebay_search_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn btn-outline-secondary btn-sm"
                    >
                      Browse eBay →
                    </a>
                  )}
                  {data.resale_price_url && (
                    <a
                      href={data.resale_price_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn btn-outline-secondary btn-sm"
                    >
                      Browse {data.resale_price_source || 'resale'} →
                    </a>
                  )}
                </>
              )}
            >
              <ErrorNote of={ebayMut} className="mb-3" />
              {/* The figure the collection totals actually use, first — it is
                  the answer — with the raw inputs under it so the two can be
                  reconciled on one screen. */}
              <div className="hr-value-hero">
                <div className="hr-metric-label">Est. sale value</div>
                <div className="hr-price hr-price-large">
                  {hatValue.value != null ? money(hatValue.value) : '—'}
                </div>
                <div className="hr-value-why">{hatValue.explanation}</div>
              </div>
              {/* A reflowing grid rather than three-across: at 375px the old
                  row gave each tile ~110px, which a four-digit price and a
                  source line don't fit into. Two-up on a phone and in the
                  two-column layout, four across the single column between
                  (see hat-pages.css). */}
              <div className="hr-metric-grid hr-price-grid">
                <PriceTile
                  label="New retail"
                  value={data.estimated_new_price ?? null}
                  source={data.estimated_new_price_source}
                />
                <PriceTile
                  label="Paid"
                  value={data.purchase_price ?? null}
                  source={data.purchased_at
                    ? new Date(data.purchased_at).toLocaleDateString()
                    : 'not recorded'}
                />
                <PriceTile
                  label="eBay ask"
                  value={data.ebay_median_price ?? null}
                  source={data.ebay_listing_count != null
                    ? `median of ${data.ebay_listing_count} live listings`
                    : 'configure eBay key'}
                />
                {/* Was labeled "Resale (manual)" while holding a scraped
                    median for all but the rare hand-entered price — the label
                    named the exception. */}
                <PriceTile
                  label="Resale ask"
                  value={data.resale_price ?? null}
                  source={data.resale_price_source}
                />
              </div>
            </Panel>
          )}

          {/* Keyed on the hat so navigating between hats REMOUNTS the card.
              Without this the component instance is reused and only `notes` is
              reset by its own effect — the save error and "Saved" state are
              not, so one failed save on hat 12 left a red "Couldn't save"
              sitting under hats 13, 14 and 15's untouched, empty boxes. The
              remount is also what flushes a pending autosave to the hat it was
              typed for, not the next one. */}
          <HatNotesCard key={data.id} hat={data} />

          <Panel title="Specs">
            {/* "Type" used to sit here showing Beanie or Regular — which is
                derived entirely from Style directly above it (`is_beanie` is
                set from the style on every write), so the sheet spent a quarter
                of itself printing one fact twice.

                Construction and colorway are what actually separate two hats
                of the same style, and neither was here: construction appeared
                only as a badge by the title, and colorway appeared nowhere on
                this page at all, despite a catalog and a purchase matcher whose
                whole job is filling it in. */}
            <div className="hr-metric-grid">
              {([
                ['Style', labels.style(data.style)],
                ['Limited edition', data.limited_edition ? 'Yes' : null],
                ['Size', labels.size(data.size)],
                ['Construction', data.construction],
                ['Colorway', data.colorway],
                ['Collection', data.artist_series],
                ['Last worn', data.date_last_worn],
              ] as const).map(([label, value]) => (
                <div className="hr-metric" key={label}>
                  <div className="hr-metric-label">{label}</div>
                  <div className="hr-metric-value hr-spec-value">{value || '—'}</div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel
            title="Case"
            className={placed ? '' : 'border-warning'}
            status={!placed && <StatusPill tone="warn">Unplaced</StatusPill>}
          >
            {data.case_display_id ? (
              <div className="hr-case-summary">
                <div className="hr-case-summary-what">
                  <span className="hr-case-code">{data.case_display_id}</span>
                  {caseTypeLabel && (
                    <span className={`badge ${data.case_type === 'archive' ? 'bg-secondary' : 'bg-info'}`}>
                      {caseTypeLabel}
                    </span>
                  )}
                  {data.room_name && (
                    <span className="badge bg-info">{data.room_name}</span>
                  )}
                </div>
                <Link to={`/cases/${data.case_display_id}`} className="btn btn-outline-secondary btn-sm">View case</Link>
              </div>
            ) : data.direct_room_id ? (
              /* In a room with no case — a shelf, a hook, a stand. Not a
                 warning state: it is where the hat lives. Caddies and Aviators
                 don't fit a travel case at all. */
              <div className="hr-case-summary">
                <div>
                  <span className="badge bg-info">{data.room_name}</span>
                  <div className="text-secondary small mt-1">Kept here, not in a case</div>
                </div>
                <Link to={`/hats/${data.id}/edit`} className="btn btn-outline-secondary btn-sm">Move</Link>
              </div>
            ) : (
              <div className="hr-case-summary">
                <div className="hr-case-unplaced">Not in a case or a room</div>
                <Link to={`/hats/${data.id}/edit`} className="btn btn-outline-warning btn-sm">Assign</Link>
              </div>
            )}
          </Panel>

          {/* Colors — tap any row to edit */}
          <Panel
            title="Color palette"
            actions={(
              <>
                {data.colors.length > 0 && (
                  <button
                    type="button"
                    className="btn btn-outline-danger btn-sm"
                    onClick={() => { void confirmClearColors(data.colors.length); }}
                    disabled={clearColorsMutation.isPending}
                  >
                    {clearColorsMutation.isPending ? 'Clearing…' : 'Clear all'}
                  </button>
                )}
                <button
                  type="button"
                  className="btn btn-outline-secondary btn-sm"
                  onClick={() => setColorEditOpen(-1)}
                >
                  + Add color
                </button>
              </>
            )}
          >
            <ErrorNote of={clearColorsMutation} what="Colors not cleared" className="mb-2" />
            {data.colors.length === 0 ? (
              <p className="text-muted small mb-0">
                No colors yet — tap “Add color” to seed the palette manually, or run Reanalyze.
              </p>
            ) : (
              data.colors.map(c => (
                <button
                  key={c.dominance_rank}
                  type="button"
                  className="hr-color-row hr-color-row-btn"
                  onClick={() => setColorEditOpen(c.dominance_rank)}
                  title="Tap to edit"
                >
                  <span
                    className="color-swatch hr-color-row-swatch"
                    style={{ backgroundColor: c.hex_value, color: c.hex_value }}
                  />
                  <span className="flex-grow-1">
                    <span className="hr-color-row-name">{c.general_color || c.color_name}</span>
                    {c.color_name && c.color_name !== c.general_color && (
                      <span className="hr-color-row-sub font-mono">{c.color_name}</span>
                    )}
                  </span>
                  <span className="text-end">
                    <span className="hr-tier-label">{c.tier || 'primary'}</span>
                    <span className="hr-color-row-sub font-mono">{c.hex_value}</span>
                  </span>
                </button>
              ))
            )}
          </Panel>

          <Panel
            title="Disposition"
            status={data.disposed_at
              ? <StatusPill tone="warn">{dispositionLabel(data.disposed_via)}</StatusPill>
              : <StatusPill tone="ok">Active</StatusPill>}
            description={data.disposed_at
              ? undefined
              : 'Mark this hat as sold, gifted, traded, lost, or trashed. Soft-delete only — undoable.'}
            footer={data.disposed_at ? (
              <button
                type="button"
                className="btn btn-outline-secondary btn-sm"
                onClick={() => { void confirmRestore(); }}
                disabled={undisposeMut.isPending}
              >
                {undisposeMut.isPending ? 'Restoring…' : 'Undo — restore to active'}
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-outline-secondary btn-sm"
                onClick={() => setDisposeOpen(true)}
              >
                Mark as disposed
              </button>
            )}
          >
            {data.disposed_at && (
              <>
                <div className="hr-metric">
                  <div className="hr-metric-label">
                    {dispositionLabel(data.disposed_via)} on {new Date(data.disposed_at).toLocaleDateString()}
                  </div>
                  {data.disposed_price != null && (
                    <div className="hr-metric-value hr-price">
                      ${data.disposed_price.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                    </div>
                  )}
                  {data.disposed_to && (
                    <div className="text-secondary small mt-1">{data.disposed_to}</div>
                  )}
                  {data.disposed_notes && (
                    <div className="hr-dispose-notes">“{data.disposed_notes}”</div>
                  )}
                </div>
                <ErrorNote of={undisposeMut} className="mt-2 mb-0" />
              </>
            )}
          </Panel>

          {/* Physical tag. Sits on the hat's own page because that is where you
              are standing when you tag it — holding this hat, with a blank NFC
              sticker and a tag writer open. */}
          <Panel
            title="Tag this hat"
            description={(
              <>
                Write this to an NFC sticker, or print a QR from{' '}
                <Link to="/settings?tab=sharing">Settings</Link>. Scanning it opens a one-tap
                “wore it today” screen.
              </>
            )}
          >
            <TagUrlRow kind="h" ident={data.id} />
          </Panel>

          {/* One row, one weight each: adding the next hat, editing this one,
              deleting it. Delete used to be a full-width solid red button
              beside a small outlined Edit — the loudest control on the page
              was the one you almost never want. */}
          <div className="hr-hat-foot-actions">
            <Link to="/hats/new" className="btn btn-outline-primary">+ Add another hat</Link>
            <Link to={`/hats/${data.id}/edit`} className="btn btn-outline-secondary">Edit</Link>
            <button
              type="button"
              className="btn btn-outline-danger"
              onClick={() => { void confirmDelete(); }}
              disabled={removeMutation.isPending}
            >
              {removeMutation.isPending ? 'Deleting…' : 'Delete'}
            </button>
          </div>
          <ErrorNote of={removeMutation} className="mt-2 mb-0" />
        </div>
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
