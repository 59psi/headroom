import type { SweepProgress } from '../../types';

/**
 * Live state of a long in-process sweep — bar, counts, and what it is on.
 *
 * One component for re-pricing and the colorway harvest because they pose the
 * same question. The Analysis Queue renders its own bar from a different
 * source (job progress derived from the database, which survives a restart),
 * so it is deliberately not folded in here.
 *
 * Renders nothing when there is nothing to say. A permanently-present empty
 * bar reads as a stalled job, which is the opposite of the point.
 */
export function SweepProgressBar({ progress, idleLabel }: {
  progress: SweepProgress | undefined;
  /** Shown when a previous run finished and there is nothing in flight. */
  idleLabel?: string;
}) {
  if (!progress) return null;

  if (!progress.running) {
    // An error outlives the run that produced it — that is what makes it
    // readable at all, since nobody is watching at the moment it fails.
    if (progress.error) {
      return (
        <p className="small mb-2" style={{ color: 'var(--neon-pink)' }}>
          Last run failed: {progress.error}
        </p>
      );
    }
    return idleLabel ? <p className="text-secondary small mb-2">{idleLabel}</p> : null;
  }

  return (
    <div className="mb-3">
      <div className="d-flex justify-content-between align-items-baseline mb-1">
        <span className="small">Working…</span>
        <span className="font-mono small">
          {progress.done} / {progress.total}
        </span>
      </div>
      <div className="hr-progress mb-1">
        <div
          className="hr-progress-fill"
          style={{ width: `${progress.pct}%` }}
          role="progressbar"
          aria-label="Sweep progress"
          aria-valuenow={progress.done}
          aria-valuemin={0}
          aria-valuemax={progress.total}
        />
      </div>
      {/* The useful half. "37 of 235" says it is alive; naming the item says
          it is not wedged on one. */}
      {progress.label && (
        <div className="text-secondary small text-truncate">{progress.label}</div>
      )}
    </div>
  );
}
