import type { HatRead } from '../../types';

/**
 * The pipeline's steps in the order the backend publishes them. The position
 * in this array IS the step number rendered, so the order is load-bearing and
 * must match the `STAGE_*` constants in `hat_analysis_pipeline.py`.
 */
export const STAGES = ['cutout', 'identifying', 'pricing', 'resale'] as const;

/**
 * Two lengths on purpose. The short one is rendered beside the counter and is
 * kept to one word so the badge stays on a single line on a phone; the long one
 * is the tooltip and the accessible name, where there is room to be clear.
 */
const STAGE_SHORT: Record<string, string> = {
  cutout: 'Cutout',
  identifying: 'Identifying',
  pricing: 'Pricing',
  resale: 'Resale',
};

const STAGE_LABELS: Record<string, string> = {
  cutout: 'Removing background',
  identifying: 'Identifying the hat',
  pricing: 'Checking prices',
  resale: 'Checking resale',
};

/**
 * The badge on a hat showing where its analysis got to.
 *
 * Pending renders as "2/4 · Identifying": a counter for progress, plus a name
 * so it still says what is happening. The full phrasing ("Removing
 * background…") is what wrapped this pill onto a second line on a phone and
 * pushed the badge row down into the photo, and because the wording changed
 * every few seconds the layout moved while you were reading it — so the
 * counter is fixed-width and the name is clipped to one word rather than
 * dropped. The long phrasing stays in the tooltip and the accessible name.
 */
export function AnalysisStatus({ hat }: { hat: HatRead }) {
  if (!hat.analysis_status) return null;
  const status = hat.analysis_status;

  if (status === 'pending') {
    const index = STAGES.indexOf(hat.analysis_stage as (typeof STAGES)[number]);
    // Before the first stage publishes there is no stage yet; showing 1/4
    // reads as "queued, about to start" rather than as a missing value.
    const step = index >= 0 ? index + 1 : 1;
    const name = (hat.analysis_stage && STAGE_LABELS[hat.analysis_stage]) || 'Analyzing';
    const short = (hat.analysis_stage && STAGE_SHORT[hat.analysis_stage]) || 'Analyzing';
    return (
      <span
        className="hr-analysis-status pending"
        title={`${name} — step ${step} of ${STAGES.length}`}
        aria-label={`Analyzing: ${name}, step ${step} of ${STAGES.length}`}
      >
        <span className="hr-analysis-step">{step}/{STAGES.length}</span>
        {short}
      </span>
    );
  }

  const label =
    status === 'ok' ? 'Analyzed'
    : status === 'skipped' ? 'No API key'
    : status === 'fallback' ? 'Basic ID'
    : 'Failed';
  return (
    <span className={`hr-analysis-status ${status}`} title={hat.analysis_error || undefined}>
      <span className="dot" />
      {label}
    </span>
  );
}
