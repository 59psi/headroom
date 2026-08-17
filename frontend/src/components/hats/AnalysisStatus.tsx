import type { HatRead } from '../../types';

/**
 * The pipeline's steps in the order the backend publishes them. The position
 * in this array IS the step number rendered, so the order is load-bearing and
 * must match the `STAGE_*` constants in `hat_analysis_pipeline.py`.
 */
export const STAGES = ['cutout', 'identifying', 'pricing', 'resale'] as const;

/** Long-form step names — the tooltip, and the screen-reader label. */
const STAGE_LABELS: Record<string, string> = {
  cutout: 'Removing background',
  identifying: 'Identifying the hat',
  pricing: 'Checking prices',
  resale: 'Checking resale',
};

/**
 * The badge on a hat showing where its analysis got to.
 *
 * Pending renders as a bare "2/4" rather than naming the step. The names run to
 * ~22 characters, which wrapped this pill onto a second line on a phone and
 * pushed the badge row down into the photo — and the name changes every few
 * seconds, so the layout moved while you were reading it. A counter is
 * fixed-width, monotonic, and answers the question the badge is actually there
 * to answer: is it moving, and how much is left. The full step name stays in
 * the tooltip and the accessible label.
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
    return (
      <span
        className="hr-analysis-status pending"
        title={`${name} — step ${step} of ${STAGES.length}`}
        aria-label={`Analyzing: ${name}, step ${step} of ${STAGES.length}`}
      >
        {step}/{STAGES.length}
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
