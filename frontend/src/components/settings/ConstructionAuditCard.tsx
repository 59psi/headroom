import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { auditConstructions, clearConstruction } from '../../api/settings';
import type { ConstructionClearResult } from '../../types';

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
  const { data } = useQuery({
    queryKey: ['admin', 'construction-audit'],
    queryFn: auditConstructions,
  });
  const [preview, setPreview] = useState<ConstructionClearResult | null>(null);
  // What the matched hats become. Blank clears the field; the common case is
  // not "I don't know" but "these are all actually HYDRO", and clearing would
  // discard a correction the owner already knows how to make.
  const [target, setTarget] = useState('');

  const dryRun = useMutation({
    mutationFn: (value: string) => clearConstruction(value, true, target || null),
    onSuccess: setPreview,
  });
  const apply = useMutation({
    mutationFn: (value: string) => clearConstruction(value, false, target || null),
    onSuccess: () => {
      setPreview(null);
      qc.invalidateQueries({ queryKey: ['admin', 'construction-audit'] });
      qc.invalidateQueries({ queryKey: ['hats'] });
      qc.invalidateQueries({ queryKey: ['hat'] });
    },
  });

  return (
    <div className="card mb-3">
      <div className="card-body">
        <h5 className="card-title">Construction audit</h5>
        <p className="text-secondary small">
          Analysis used to fill this field from the photo, and it reads HYDRO vs
          HYDROLite unreliably — the tells don't survive a front-on shot. It no
          longer writes the field at all, but values it already wrote are still
          here, and nothing recorded which came from you. Clearing one also
          removes the model-name suffix and any price the table derived from it.
        </p>

        <div className="mb-3">
          <label className="form-label small" htmlFor="construction-target">
            Change them to
          </label>
          <input
            id="construction-target"
            aria-label="Change them to"
            className="form-control form-control-sm font-mono"
            placeholder="HYDRO — or leave blank to clear the field"
            value={target}
            onChange={e => setTarget(e.target.value)}
            style={{ maxWidth: 320 }}
          />
        </div>

        {!data?.length && <p className="text-secondary small mb-0">No constructions recorded.</p>}

        {!!data?.length && (
          <div className="table-responsive">
            <table className="table table-sm align-middle mb-0">
              <thead>
                <tr>
                  <th>Construction</th>
                  <th className="text-end">Hats</th>
                  <th className="text-end">Priced from it</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.map(row => (
                  <tr key={row.construction}>
                    <td className="font-mono">{row.construction}</td>
                    <td className="text-end">{row.hat_count}</td>
                    <td className="text-end">{row.priced_from_table}</td>
                    <td className="text-end">
                      <button
                        type="button"
                        className="btn btn-outline-danger btn-sm"
                        disabled={dryRun.isPending}
                        onClick={() => dryRun.mutate(row.construction)}
                      >Clear…</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {preview && (
          <div className="alert alert-warning mt-3 small">
            <div className="fw-semibold mb-1">
              {preview.to
                ? <>Change “{preview.construction}” to “{preview.to}” on </>
                : <>Clear “{preview.construction}” from </>}
              {preview.hats_cleared} hat{preview.hats_cleared === 1 ? '' : 's'}?
            </div>
            <ul className="mb-2">
              <li>{preview.model_names_corrected} model name(s) lose the suffix</li>
              <li>
                {preview.prices_cleared} price(s){' '}
                {preview.to ? 're-looked-up from the new value' : 'cleared'}
              </li>
              <li>{preview.manual_prices_kept} price(s) you entered are kept</li>
              <li>
                <strong>{preview.owner_set_skipped}</strong> left alone because
                you set them yourself
              </li>
            </ul>
            {!!preview.samples.length && (
              <div className="text-secondary mb-2 font-mono">
                {preview.samples.join(', ')}
                {preview.hats_cleared > preview.samples.length && ' …'}
              </div>
            )}
            <div className="d-flex gap-2">
              <button
                type="button"
                className="btn btn-danger btn-sm"
                disabled={apply.isPending || preview.hats_cleared === 0}
                onClick={() => apply.mutate(preview.construction)}
              >{apply.isPending ? 'Clearing…' : 'Clear them'}</button>
              <button
                type="button"
                className="btn btn-outline-secondary btn-sm"
                onClick={() => setPreview(null)}
              >Cancel</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
