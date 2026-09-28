import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate, Link } from 'react-router';
import { getHat, deleteHat, uploadHatPhoto, reanalyzeHat, recutHat, refreshEbayForHat, undisposeHat, updateHatColors } from '../api/hats';
import { getApiKeyStatus } from '../api/settings';
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
import { useEffect, useState } from 'react';
import { hatViewKeys, invalidateAll, invalidateHatViews } from '../lib/invalidate';
import { qk } from '../lib/queryKeys';
import { hatName } from '../lib/placement';
import { ErrorNote } from '../components/common/ErrorNote';
import { isNotFound } from '../api/client';
import { costOf, money, moneyPrecise, valueHat } from '../lib/valuation';
import { caseTypeName } from '../lib/caseTypes';
import { formatDateOnly } from '../lib/dates';
import { uploadUrl } from '../lib/photo';
import { useWearLog } from '../lib/useWearLog';
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
 * What re-analysis keeps and what it rewrites, said where the button is.
 *
 * The single Reanalyze has no confirmation (it is undoable in the sense that
 * matters: nothing typed is lost), so the one line that would have been in a
 * confirm dialog sits under it instead. Same words as the whole-collection
 * re-analyze confirm in Settings.
 */
export const REANALYZE_KEEPS =
  'Prices you entered by hand and colors you edited are kept. Model names and design notes are rewritten from the photo.';

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
  // A hat outside a case has no display_id at all — nothing to link to, so
  // it goes by the name every other screen gives it (`hatName`: its model,
  // then "Hat #12"), and that name is not dressed up as navigation.
  if (!caseId || !hat.display_id?.startsWith(caseId)) {
    return <>{hatName(hat)}</>;
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
          <div className="hr-metric-value hr-price">{money(value)}</div>
          {source && <div className="hr-metric-source">{source}</div>}
        </>
      ) : (
        <div className="hr-metric-value hr-metric-empty">—</div>
      )}
    </div>
  );
}

/**
 * Which color the editor is open on: adding one, or editing the swatch at a
 * rank. Named states rather than a number whose sentinels (`-1` for adding,
 * `null` for closed) had to be decoded from a comment.
 */
type ColorEditor = { mode: 'add' } | { mode: 'edit'; rank: number };

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
  const [colorEditor, setColorEditor] = useState<ColorEditor | null>(null);
  // The hat this page has just deleted, so its row can leave the cache with
  // the page (below).
  const [deletedId, setDeletedId] = useState<number | null>(null);

  const id = Number(hatId);
  const hatQ = useQuery({
    queryKey: qk.hat(id),
    queryFn: () => getHat(id),
    enabled: !isNaN(id),
    // Analysis runs on a background worker, so the result arrives after this
    // page has already rendered. Poll while it's pending — and while a re-cut
    // is in flight, which keeps the hat's status (its identification still
    // stands) but reports `analysis_stage` until the new cutout lands; polling
    // on status alone left the old photo up until something else refetched.
    // Returning false is what ends the polling, so a hat that finishes, errors
    // or is skipped is not hammered forever.
    refetchInterval: query => {
      const hat = query.state.data;
      return hat && (hat.analysis_status === 'pending' || hat.analysis_stage != null) ? 2000 : false;
    },
  });
  const data = hatQ.data;

  // Whether a Claude key exists decides what the skipped and fallback banners
  // advise. Same key the Add hat page and the Settings key card use, so it is
  // usually cached already.
  const apiKey = useQuery({ queryKey: qk.settings.apiKey(), queryFn: getApiKeyStatus });
  const keyMissing = apiKey.data?.configured === false;
  const keyKnown = apiKey.data !== undefined;

  // A deleted hat's row leaves the cache with the page — not before: the
  // navigation away is a transition, so this page renders again first, and
  // a query whose row was already removed is rebuilt and FETCHED on that
  // render. Left in the cache for good, Back from the list would open the
  // deleted hat from cache as if it still existed.
  useEffect(() => {
    if (deletedId === null) return;
    return () => { qc.removeQueries({ queryKey: qk.hat(deletedId), exact: true }); };
  }, [deletedId, qc]);

  /**
   * Show the server's fresh row now, then refresh everywhere else it shows.
   *
   * Every mutation on this page takes the hat it acts on as its VARIABLE and
   * settles against that, never against the render's `id`: React Router keeps
   * this page mounted from one hat to the next (Back from hat 13 lands on hat
   * 12 with the same instance), and TanStack hands a running mutation the
   * LATEST render's options. A closure over `id` put a re-cut started on hat
   * 12 into hat 13's cache, and invalidated 13 while 12 kept its stale row.
   * `res` is optional only because a test double may answer nothing.
   */
  function settle(res: HatRead | undefined, hatId: number) {
    if (res) qc.setQueryData(qk.hat(hatId), res);
    return invalidateHatViews(qc, hatId);
  }

  const removeMutation = useMutation({
    mutationFn: (hatId: number) => deleteHat(hatId),
    onSuccess: (_void, hatId) => {
      setDeletedId(hatId);
      toast.success('Hat deleted');
      navigate('/hats');
      // Every view a hat change shows in, LESS the hat pages: `hatViewKeys`
      // names the detail key too, and the page still observing it refetched
      // a hat that was gone — a 404 after every delete. No other hat's page
      // shows this one.
      void invalidateAll(qc, hatViewKeys().filter(key => key[0] !== qk.hat()[0]));
    },
  });

  const recutMut = useMutation({
    mutationFn: (hatId: number) => recutHat(hatId),
    onSuccess: (res, hatId) => {
      void settle(res, hatId);
      toast.info('Redoing the cutout from the original photo');
    },
  });

  const reanalyzeMut = useMutation({
    mutationFn: (hatId: number) => reanalyzeHat(hatId),
    onSuccess: (res, hatId) => {
      void settle(res, hatId);
      // With a key the work is queued and the badge takes over; without one
      // the fallback ran inline and this response IS the result.
      toast.info(res?.analysis_status === 'pending' ? 'Reanalysis started' : 'Reanalysis finished');
    },
  });

  // Every write on this page goes through `useMutation` and renders `.error`.
  // Five of them used to be bare `await`s in click handlers (this upload, the
  // eBay refresh, undispose, and — in their own cards — passkey removal and
  // share-link revoke): a 413 from the photo cap, a dropped LAN, a 502 from
  // eBay each vanished into an unhandled rejection and the button simply
  // un-pressed itself.
  const uploadMut = useMutation({
    mutationFn: (vars: { hatId: number; file: File }) => uploadHatPhoto(vars.hatId, vars.file),
    onSuccess: (res, { hatId }) => {
      void settle(res, hatId);
      toast.success('Photo uploaded');
    },
  });
  const ebayMut = useMutation({
    mutationFn: (hatId: number) => refreshEbayForHat(hatId),
    onSuccess: (_res, hatId) => {
      void qc.invalidateQueries({ queryKey: qk.hat(hatId) });
      toast.success('eBay prices refreshed');
    },
  });
  const undisposeMut = useMutation({
    mutationFn: (hatId: number) => undisposeHat(hatId),
    onSuccess: (res, hatId) => {
      void settle(res, hatId);
      toast.success('Hat restored to active');
    },
  });

  // Wipe the whole palette in one call — PUT /colors replaces the set, so an
  // empty list IS the delete-all, and hands the colors back to analysis (a
  // later Reanalyze rebuilds them from the photo). Beats removing swatches one
  // modal at a time after a bad analysis.
  //
  // Optimistic: the answer to "replace the colors with none" is no colors,
  // so the palette empties the moment you confirm. A failure puts the old
  // palette back and says so under the card's header.
  const clearColorsMutation = useMutation({
    mutationFn: (hatId: number) => updateHatColors(hatId, []),
    onMutate: async (hatId: number) => {
      // A poll landing mid-flight would repaint the old palette over the
      // optimistic one.
      await qc.cancelQueries({ queryKey: qk.hat(hatId) });
      const previous = qc.getQueryData<HatRead>(qk.hat(hatId));
      if (previous) qc.setQueryData<HatRead>(qk.hat(hatId), { ...previous, colors: [] });
      return { previous };
    },
    onError: (_err, hatId, ctx) => {
      if (ctx?.previous) qc.setQueryData(qk.hat(hatId), ctx.previous);
    },
    onSuccess: () => toast.success('Colors cleared'),
    // Not returned: TanStack holds a mutation's error/success state until a
    // returned `onSettled` promise resolves, which would keep "Clearing…" up
    // and the failure unsaid until every list had refetched. The optimistic
    // state already shows the outcome.
    onSettled: (_res, _err, hatId) => { void invalidateHatViews(qc, hatId); },
  });

  const { wearMut, undoMut: undoWearMut } = useWearLog();

  async function confirmDelete(hatId: number) {
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
    if (ok) removeMutation.mutate(hatId);
  }

  async function confirmClearColors(hatId: number, count: number) {
    const ok = await confirm({
      title: `Remove all ${count} colors from this hat?`,
      body: 'You can add them back by hand, or reanalyze to rebuild the palette from the photo.',
      confirmLabel: 'Clear colors',
      tone: 'danger',
    });
    if (ok) clearColorsMutation.mutate(hatId);
  }

  async function confirmRestore(hatId: number) {
    const ok = await confirm({
      title: 'Restore this hat to active inventory?',
      body: 'It goes back to its case — or to unassigned, if that case has filled up since.',
      confirmLabel: 'Restore',
    });
    if (ok) undisposeMut.mutate(hatId);
  }

  if (hatQ.isLoading) return <HatDetailSkeleton />;
  // Only a 404 is "not found". A locked database or a dead server used to
  // render the same "may have been deleted" copy — the opposite of the truth.
  if (hatQ.error && !isNotFound(hatQ.error)) return (
    <div className="py-4">
      <ErrorNote of={hatQ} what="Could not load this hat" />
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

  // Plain calls, not hooks — pure and cheap, and here they sit below the
  // `!data` guard without needing a null-safe variant.
  const hatValue = valueHat(data);
  const paid = costOf(data);
  const placed = Boolean(data.case_display_id || data.direct_room_id);
  // A re-cut keeps the hat's analysis status and reports only its stage.
  const recutting = data.analysis_stage === 'cutout' && data.analysis_status !== 'pending';

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
                <ImageLightbox src={uploadUrl(data.photo_path)} alt={hatName(data)} hat />
              ) : (
                <PhotoCapture onCapture={file => uploadMut.mutate({ hatId: data.id, file })} previewUrl={null} />
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
                  <PhotoCapture onCapture={file => uploadMut.mutate({ hatId: data.id, file })} hidePreview />
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
                    onClick={() => reanalyzeMut.mutate(data.id)}
                    disabled={reanalyzeMut.isPending}
                    aria-describedby="hat-reanalyze-keeps"
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
                    onClick={() => recutMut.mutate(data.id)}
                    disabled={recutMut.isPending || recutting || data.analysis_status === 'pending'}
                    title="Redo the background removal from the original photo"
                  >
                    {recutMut.isPending || recutting ? '✂ Re-cutting…' : '✂ Redo cutout'}
                  </button>
                )}
              </div>
              {data.photo_path && (
                <p className="hr-hero-note" id="hat-reanalyze-keeps">{REANALYZE_KEEPS}</p>
              )}

              <div className="hr-wear-line">
                <span>Worn <strong>{data.wear_count}×</strong></span>
                {data.date_last_worn && <span>last {data.date_last_worn}</span>}
                {/* Cost per wear needs what was PAID — `costOf`, the same
                    rule the Stats leaderboard ranks by, so a hat with no
                    recorded price (or a $0 gift) shows nothing here rather
                    than a figure that page leaves out. It used to fall back
                    to the estimated retail price, which answers a different
                    question: a hat bought half-price showed a cost per wear
                    it never had. */}
                {data.wear_count > 0 && paid != null && (
                  <span>{moneyPrecise(paid / data.wear_count)}/wear</span>
                )}
                {data.wear_count > 0 && (
                  <button
                    type="button"
                    className="btn btn-link btn-sm hr-wear-undo"
                    aria-label="Undo the last logged wear"
                    onClick={() => undoWearMut.mutate(data.id)}
                    disabled={undoWearMut.isPending || wearMut.isPending}
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
              reason a card is thin is read before the thin card. Each says
              what to do NEXT, which depends on whether a key exists now — a
              hat skipped at upload for want of a key stays "skipped" after
              one is added, and "add a key" is then the wrong advice. */}
          {/* Until the key status arrives, neither piece of advice: each is
              wrong for one of the two answers, and a banner that flips from
              "Tap Reanalyze" to "configure your key" a moment after the page
              loads reads as the app changing its mind. */}
          {data.analysis_status === 'skipped' && (
            <div className="alert alert-info mb-3">
              {keyMissing ? (
                <>
                  Configure your Anthropic API key in{' '}
                  <Link to="/settings?tab=analysis" className="hr-alert-link">Settings</Link>{' '}
                  to enable AI brand, color and price detection.
                </>
              ) : keyKnown ? (
                <>This hat was added before analysis could run. Tap Reanalyze to identify it.</>
              ) : (
                <>This hat has not been analyzed yet.</>
              )}
            </div>
          )}

          {/* Fallback means "Claude did not answer", which has more than one
              cause, and this banner once asserted the wrong one: it said "add
              a Claude API key" unconditionally — so when the Anthropic
              account ran out of CREDIT, every hat in the collection told its
              owner to add the key that was already there. The key advice
              comes from whether a key is configured NOW (`keyMissing`), never
              from the absence of an error, which the fallback path always
              writes; with no key that is the whole answer, since any
              reanalysis would fall back again. Otherwise the reason is
              `analysis_error`, shown as the server wrote it. Never both: the
              server's text for a keyless hat carries the same "add a key"
              sentence, and the banner used to print it twice. */}
          {data.analysis_status === 'fallback' && (
            <div className="alert alert-info mb-3 small">
              Basic fallback ID only (colors from the photo cutout{data.brand ? ', brand from logo detection' : ''}).
              {keyMissing ? (
                <>
                  {' '}No Claude API key is set — add one in{' '}
                  <Link to="/settings?tab=analysis" className="hr-alert-link">Settings</Link>
                  {' '}and hit Reanalyze for full model + price identification.
                </>
              ) : data.analysis_error && (
                <>
                  {' '}<strong>Why:</strong> {data.analysis_error}
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
                  onClick={() => ebayMut.mutate(data.id)}
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
                {/* A calendar date, printed as the date that was entered: the
                    form stores midnight of that day and the API returns it as
                    UTC, and formatting that instant put the purchase on the day
                    BEFORE everywhere west of Greenwich — while the Edit form
                    beside it showed the right one. "Date not recorded" rather
                    than "not recorded", which read as the price being missing. */}
                <PriceTile
                  label="Paid"
                  value={data.purchase_price ?? null}
                  source={data.purchased_at ? formatDateOnly(data.purchased_at) : 'date not recorded'}
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
                  {data.case_type && (
                    <span className={`badge ${data.case_type === 'archive' ? 'bg-secondary' : 'bg-info'}`}>
                      {caseTypeName(data.case_type)}
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
            description={data.colors_source === 'owner'
              ? 'Set by you — re-analysis keeps these. Remove every color to hand them back to analysis.'
              : undefined}
            actions={(
              <>
                {data.colors.length > 0 && (
                  <button
                    type="button"
                    className="btn btn-outline-danger btn-sm"
                    onClick={() => { void confirmClearColors(data.id, data.colors.length); }}
                    disabled={clearColorsMutation.isPending}
                  >
                    {clearColorsMutation.isPending ? 'Clearing…' : 'Clear all'}
                  </button>
                )}
                <button
                  type="button"
                  className="btn btn-outline-secondary btn-sm"
                  onClick={() => setColorEditor({ mode: 'add' })}
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
                  onClick={() => setColorEditor({ mode: 'edit', rank: c.dominance_rank })}
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
                    {/* The tier as stored: the server publishes it as one of
                        its four values, whoever wrote the color. */}
                    <span className="hr-tier-label">{c.tier}</span>
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
                onClick={() => { void confirmRestore(data.id); }}
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
                  {/* To the cent: this is one sale's actual proceeds, not an
                      estimate rounded for a total. */}
                  {data.disposed_price != null && (
                    <div className="hr-metric-value hr-price">
                      {moneyPrecise(data.disposed_price)}
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
              onClick={() => { void confirmDelete(data.id); }}
              disabled={removeMutation.isPending}
            >
              {removeMutation.isPending ? 'Deleting…' : 'Delete'}
            </button>
          </div>
          <ErrorNote of={removeMutation} className="mt-2 mb-0" />
        </div>
      </div>

      <DisposeModal hatId={data.id} show={disposeOpen} onClose={() => setDisposeOpen(false)} />
      {colorEditor && (
        <ColorEditModal
          hatId={data.id}
          colors={data.colors}
          editingRank={colorEditor.mode === 'edit' ? colorEditor.rank : null}
          onClose={() => setColorEditor(null)}
        />
      )}
    </>
  );
}
