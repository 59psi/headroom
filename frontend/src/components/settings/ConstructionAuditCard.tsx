import { useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { auditConstructions, clearConstruction } from '../../api/settings';
import type { ConstructionClearResult } from '../../types';
import { noun, plural } from '../../lib/format';
import { invalidateHatViews, invalidateHatVocabulary } from '../../lib/invalidate';
import { qk } from '../../lib/queryKeys';
import { ErrorNote } from '../common/ErrorNote';
import { Panel } from '../ui/Panel';
import { StatusPill } from '../ui/StatusPill';
import { Skeleton } from '../ui/Skeleton';
import { useToast } from '../ui/Toast';

/**
 * Review constructions and undo ones analysis guessed.
 *
 * Until 2.32 the pipeline filled `construction` from the photo whenever the
 * field was empty, and Claude reads HYDRO vs HYDROLite unreliably — the tells
 * are bonded seams, a gel-welded logo and a sweatband, none of which survive a
 * front-on shot. Nothing recorded which values came from a person, so which
 * ones are wrong is a judgment only the owner can make: this previews, then
 * acts on an explicit confirmation.
 */
export function ConstructionAuditCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const audit = useQuery({
    queryKey: qk.admin.constructionAudit(),
    queryFn: auditConstructions,
  });
  const data = audit.data;
  const [preview, setPreview] = useState<ConstructionClearResult | null>(null);
  // What the matched hats become. Blank clears the field; the common case is
  // not "I don't know" but "these are all actually HYDRO", and clearing would
  // discard a correction the owner already knows how to make.
  const [target, setTarget] = useState('');
  // Bumped on every edit of the target box. Clearing `preview` on an edit
  // only retires a preview that is already UP; a dry run still in flight
  // would land a moment later with a plan for the old target — "Clear
  // “HYDROLite”…?" under a box that now says HYDRO. Each dry run carries the
  // count it started under, and a result from before the latest edit is
  // dropped rather than shown.
  const edits = useRef(0);

  const dryRun = useMutation({
    // `to` arrives as a variable, fixed at the press, rather than read from
    // the box inside the request — the same rule as `apply` below. It is
    // trimmed there: a whitespace-only target is truthy, so it used to be sent
    // as a `to` of "  " rather than read as the blank that means "clear".
    mutationFn: ({ value, to }: { value: string; to: string | null; edit: number }) =>
      clearConstruction(value, true, to),
    onSuccess: (result, { edit }) => {
      if (edit === edits.current) setPreview(result);
    },
  });
  const apply = useMutation({
    // Applies exactly what the preview showed — the construction AND the
    // target the server echoed back (already canonicalized) — rather than
    // re-reading the text box. Reading the box let an edit made after the
    // preview apply a value nobody had previewed.
    mutationFn: (p: ConstructionClearResult) => clearConstruction(p.construction, false, p.to),
    onSuccess: result => {
      setPreview(null);
      toast.success(result.to
        ? `Changed “${result.construction}” to “${result.to}” on ${plural(result.hats_cleared, 'hat')}`
        : `Cleared “${result.construction}” from ${plural(result.hats_cleared, 'hat')}`);
      qc.invalidateQueries({ queryKey: qk.admin.constructionAudit() });
      // A construction change rewrites HYDRO / HYDROLite flags and table
      // prices on every hat carrying it — including the loose hats a room
      // page lists and the values the valuation totals. This used to refresh
      // `['hats']` and `['hat']` by hand, the pair RepricingCard's history
      // records as missing the case, room and search views.
      void invalidateHatViews(qc);
      // A cleared or renamed construction changes what the picker suggests.
      invalidateHatVocabulary(qc);
    },
  });

  const totalHats = (data ?? []).reduce((n, row) => n + row.hat_count, 0);
  const verb = target.trim() ? 'Change' : 'Clear';

  return (
    <Panel
      title="Construction audit"
      status={audit.isSuccess && (data?.length
        ? <StatusPill tone="info">{plural(totalHats, 'hat')}</StatusPill>
        : <StatusPill tone="ok">Nothing to do</StatusPill>)}
      description="Undo construction values analysis guessed from photos — it can't tell HYDRO from HYDROLite front-on."
      help={
        <>
          <p>
            Analysis used to fill this field from the photo, and it reads HYDRO vs
            HYDROLite unreliably — the tells (bonded seams, a gel-welded logo, a
            sweatband) don&rsquo;t survive a front-on shot. It no longer writes the
            field at all, but values it already wrote are still here, and nothing
            recorded which came from you.
          </p>
          <p>
            Clearing one also removes the model-name suffix and any price the table
            derived from it. Type a value in <em>Change them to</em> to rewrite them
            instead of clearing. Every change is previewed first, and hats you set
            yourself are left alone.
          </p>
        </>
      }
    >
      <div className="mb-3">
        <label className="form-label" htmlFor="construction-target">
          Change them to
        </label>
        {/* The "or leave blank" half used to be the tail of the placeholder,
            which a phone-width mono field cut off mid-word. */}
        <input
          id="construction-target"
          className="form-control font-mono hr-sd-narrow"
          placeholder="HYDRO"
          aria-describedby="construction-target-hint"
          value={target}
          onChange={e => {
            edits.current += 1;
            setTarget(e.target.value);
            // A preview describes the target it was run with. Leaving it up
            // while the box says something else shows one plan and labels the
            // button with another.
            setPreview(null);
          }}
          autoComplete="off"
        />
        <div id="construction-target-hint" className="hr-sd-legend mt-1">
          What the hats become. Leave blank to clear the field instead.
        </div>
      </div>

      {audit.isLoading && <Skeleton lines={3} />}
      <ErrorNote of={[audit, dryRun, apply]} className="mb-2" />
      {audit.isSuccess && !data?.length && (
        <p className="text-secondary small mb-0">No constructions recorded.</p>
      )}

      {/* Rows, not a four-column table: at phone width the table scrolled
          sideways and clipped the one button in each row. The counts ride
          under the value as one line, which is how they are read anyway. */}
      {!!data?.length && (
        <ul className="hr-sd-rows">
          {data.map(row => {
            const checking = dryRun.isPending && dryRun.variables?.value === row.construction;
            return (
              <li key={row.construction}>
                <span className="hr-sd-row-stack">
                  <span className="font-mono">{row.construction}</span>
                  <span className="hr-sd-legend">
                    {plural(row.hat_count, 'hat')} · {row.priced_from_table} priced from it
                  </span>
                </span>
                <button
                  type="button"
                  className="btn btn-outline-danger btn-sm"
                  aria-label={`${verb} ${row.construction}…`}
                  disabled={dryRun.isPending}
                  onClick={() => dryRun.mutate({
                    value: row.construction,
                    to: target.trim() || null,
                    edit: edits.current,
                  })}
                >{checking ? 'Checking…' : `${verb}…`}</button>
              </li>
            );
          })}
        </ul>
      )}

      {preview && (
        <div className="hr-sd-preview is-warn mt-3" role="region" aria-label="Preview">
          <div className="fw-semibold mb-2">
            {preview.to
              ? <>Change “{preview.construction}” to “{preview.to}” on </>
              : <>Clear “{preview.construction}” from </>}
            {plural(preview.hats_cleared, 'hat')}?
          </div>
          <ul className="hr-sd-preview-list">
            <li>
              {plural(preview.model_names_corrected, 'model name')}{' '}
              {noun(preview.model_names_corrected, 'loses', 'lose')} the suffix
            </li>
            <li>
              {plural(preview.prices_cleared, 'price')}{' '}
              {preview.to ? 're-looked-up from the new value' : 'cleared'}
            </li>
            <li>
              {plural(preview.manual_prices_kept, 'price')} you entered{' '}
              {noun(preview.manual_prices_kept, 'is', 'are')} kept
            </li>
            <li>
              <strong>{preview.owner_set_skipped}</strong> left alone because
              you set them yourself
            </li>
          </ul>
          {!!preview.samples.length && (
            <div className="text-secondary small mb-2 font-mono hr-sd-samples">
              {preview.samples.join(', ')}
              {preview.hats_cleared > preview.samples.length && ' …'}
            </div>
          )}
          <div className="d-flex gap-2 flex-wrap">
            <button
              type="button"
              className="btn btn-danger btn-sm"
              disabled={apply.isPending || preview.hats_cleared === 0}
              onClick={() => apply.mutate(preview)}
            >{apply.isPending ? (preview.to ? 'Changing…' : 'Clearing…') : (preview.to ? 'Change them' : 'Clear them')}</button>
            <button
              type="button"
              className="btn btn-outline-secondary btn-sm"
              disabled={apply.isPending}
              onClick={() => setPreview(null)}
            >Cancel</button>
          </div>
        </div>
      )}
    </Panel>
  );
}
