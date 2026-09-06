import { copyText } from '../../lib/clipboard';
import { useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  importPurchases, listPurchases, previewImport, rematchPurchases, unmatchAllPurchases,
} from '../../api/purchases';
import type { ImportPreview } from '../../types';
import { invalidateHatViews, invalidatePurchaseDerived } from '../../lib/invalidate';

/** Accepts either a bare array of line items or `{items: [...]}`. */
function readItems(text: string): Record<string, unknown>[] {
  const parsed = JSON.parse(text);
  const items = Array.isArray(parsed) ? parsed : parsed?.items;
  if (!Array.isArray(items)) {
    throw new Error('Expected a JSON array of order line items, or {"items": [...]}.');
  }
  return items;
}

/** The prompt handed to Claude or ChatGPT to turn an inbox into importable JSON.
 *
 * Every field name here is one `catalog_service` actually reads
 * (`_line_fields`, `_units_to_add`, and the `Purchase(...)` construction) —
 * notably `order_date`, not `purchased_at`. A prompt that names a field the
 * importer ignores fails silently: the import succeeds, the data is simply
 * absent, and nothing says so. `tests/test_purchase_prompt_parity.py` pins the field set.
 */
const EMAIL_IMPORT_PROMPT = `Search my email for melin order confirmations and receipts.

For every ORDER LINE — not every order — produce one JSON object. Return a
single JSON object of this exact shape and nothing else. No explanation, no
markdown code fence:

{"items": [ {...}, {...} ]}

Fields for each line:
  item_title  (required) the product line exactly as printed on the receipt,
              e.g. "Odysea Packable Hydro - Hickory Denim"
  colorway    the colorway, when the receipt lists it separately from the name
  size        e.g. "Classic", "Small"
  quantity    whole number; a line reading "x 2" is quantity 2
  price       per-unit price as a number, no currency symbol
  order_ref   the order number
  order_date  ISO 8601, e.g. "2026-03-14"

Rules:
- One object per order line. Do not merge similar lines together, and do not
  deduplicate across orders — order_ref, price and size are what tell two
  genuinely separate purchases apart.
- Include travel cases and accessories as their own lines. Do not filter
  anything out for looking like it isn't a hat.
- Never guess. If a field is not visible on the receipt, leave it out entirely
  rather than inventing a value. An omitted field is fine; a wrong one is not.
- Output only the JSON.`;

/** Copyable prompt, collapsed by default — it is long, and most visits to this
 *  card are not the one time you set up the import. */
function EmailPromptDisclosure() {
  const [copied, setCopied] = useState(false);

  async function copy() {
    // `copyText` carries the plain-HTTP fallback; the prompt is on screen and
    // selectable either way, so a refusal costs the convenience, not the feature.
    if (await copyText(EMAIL_IMPORT_PROMPT)) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } else {
      setCopied(false);
    }
  }

  return (
    <details className="hr-prompt-details mb-3">
      <summary className="text-secondary small">
        No JSON yet? Get one from your email
      </summary>
      <div className="mt-2">
        <p className="text-secondary small mb-2">
          Paste this into Claude or ChatGPT with access to your mail. It reads your
          melin receipts and returns the JSON this card imports.
        </p>
        <button
          type="button"
          className="btn btn-outline-primary btn-sm mb-2"
          onClick={copy}
        >
          {copied ? 'Copied' : 'Copy prompt'}
        </button>
        <pre className="hr-prompt-text font-mono">{EMAIL_IMPORT_PROMPT}</pre>
      </div>
    </details>
  );
}

export function PurchasesCard() {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  // The parsed file is held here until it is either imported or discarded.
  // Re-reading it on confirm would mean the preview and the import could see
  // two different files if the picker were touched in between.
  const [staged, setStaged] = useState<{ name: string; items: Record<string, unknown>[] } | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [readError, setReadError] = useState<string | null>(null);

  const purchases = useQuery({
    queryKey: ['admin', 'purchases'],
    queryFn: listPurchases,
  });

  const reset = () => {
    setStaged(null);
    setPreview(null);
    setReadError(null);
    if (fileRef.current) fileRef.current.value = '';
  };

  // Preview first, always. Importing runs the matcher, which writes colorways
  // and cost bases onto hats, and there is no undo for that beyond
  // `unmatch-all`. A dry run costs one round trip.
  const previewMut = useMutation({
    mutationFn: previewImport,
    onSuccess: setPreview,
  });

  const importMut = useMutation({
    mutationFn: importPurchases,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'purchases'] });
      invalidatePurchaseDerived(qc);
      invalidateHatViews(qc);
      reset();
    },
  });

  const rematchMut = useMutation({
    mutationFn: rematchPurchases,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'purchases'] });
      invalidatePurchaseDerived(qc);
      invalidateHatViews(qc);
    },
  });

  const unmatchMut = useMutation({
    mutationFn: unmatchAllPurchases,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'purchases'] });
      invalidatePurchaseDerived(qc);
      invalidateHatViews(qc);
    },
  });

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setReadError(null);
    setPreview(null);
    try {
      const items = readItems(await file.text());
      setStaged({ name: file.name, items });
      previewMut.mutate(items);
    } catch (err) {
      setStaged(null);
      setReadError(err instanceof Error ? err.message : 'Could not read that file.');
    }
  };

  const rows = purchases.data ?? [];
  const linked = rows.filter(r => r.hat_id != null).length;
  const busy = previewMut.isPending || importMut.isPending;

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Purchase History</div>
        <p className="text-secondary small mb-3">
          Order line items from your Melin order emails. Matching sets a hat's colorway
          and cost basis — what you actually paid — so the valuation can show a real
          gain rather than a guess.
        </p>

        <EmailPromptDisclosure />

        <div className="d-flex gap-2 align-items-center flex-wrap mb-2">
          <span className="text-secondary small font-mono">
            {rows.length} purchases · {linked} linked to hats
          </span>
        </div>

        <div className="d-flex gap-2 flex-wrap mb-2">
          <button
            type="button"
            className="btn btn-outline-primary btn-sm"
            onClick={() => fileRef.current?.click()}
            disabled={busy}
          >
            Import JSON…
          </button>
          {rows.length > 0 && (
            <button
              type="button"
              className="btn btn-outline-secondary btn-sm"
              onClick={() => rematchMut.mutate()}
              disabled={rematchMut.isPending}
            >
              {rematchMut.isPending ? 'Matching…' : 'Re-run matching'}
            </button>
          )}
          {linked > 0 && (
            <button
              type="button"
              className="btn btn-outline-danger btn-sm"
              onClick={() => unmatchMut.mutate()}
              disabled={unmatchMut.isPending}
            >
              Unlink all
            </button>
          )}
        </div>

        <input
          ref={fileRef}
          type="file"
          aria-label="Purchase history JSON file"
          accept="application/json,.json"
          onChange={handleFile}
          hidden
        />

        <p className="text-muted small mb-3">
          A JSON array of line items — each needs <code>item_title</code>, and may carry{' '}
          <code>order_ref</code>, <code>order_date</code>, <code>price</code>,{' '}
          <code>quantity</code> and <code>size</code>. Nothing is written until you
          confirm the preview.
        </p>

        {readError && <div className="alert alert-danger mt-3 mb-3 small">{readError}</div>}

        {staged && preview && (
          <div className="mb-3">
            <div className="text-secondary small mb-1 font-mono">{staged.name}</div>
            {preview.would_import === 0 ? (
              <p className="small mb-2">
                Nothing new to import — all {preview.duplicates} line
                {preview.duplicates === 1 ? '' : 's'} are already on record.
              </p>
            ) : (
              <p className="small mb-2">
                <strong>{preview.would_import}</strong> to import
                {preview.duplicates > 0 && <> · {preview.duplicates} already on record</>}
                {preview.unusable > 0 && <> · {preview.unusable} unusable</>}
                <br />
                <strong>{preview.would_match}</strong> would match a hat
                {preview.would_not_match > 0 && <> · {preview.would_not_match} would not</>}
                {preview.ambiguous > 0 && <> · {preview.ambiguous} ambiguous</>}
                {preview.likely_accessories > 0 && (
                  <>
                    <br />
                    <span className="text-muted">
                      {preview.likely_accessories} look like accessories (travel cases,
                      gift cards) — imported, but they will not match a hat.
                    </span>
                  </>
                )}
              </p>
            )}
            {/*
              The backlog is the part nobody asked for. Importing runs the
              matcher over EVERY unmatched purchase, not just this file's, so
              one click can write prices onto hats the file never mentioned.
              Stated in hats rather than rows because hats are what changes.
            */}
            {preview.would_match_backlog > 0 && (
              <p className="small mb-2">
                <strong>Also matches {preview.would_match_backlog} purchase
                {preview.would_match_backlog === 1 ? '' : 's'} already on record.</strong>{' '}
                Importing re-runs matching over everything unmatched, so this writes a
                colorway and cost basis onto {preview.would_match_total} hat
                {preview.would_match_total === 1 ? '' : 's'} in total. Unlink all is the
                only undo.
              </p>
            )}
            <div className="d-flex gap-2 flex-wrap">
              {preview.would_import > 0 && (
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => importMut.mutate(staged.items)}
                  disabled={busy}
                >
                  {importMut.isPending
                    ? 'Importing…'
                    : `Import ${preview.would_import} and match`}
                </button>
              )}
              <button
                type="button"
                className="btn btn-outline-secondary btn-sm"
                onClick={reset}
                disabled={busy}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {previewMut.isPending && (
          <div className="text-secondary small mb-2">Checking that file…</div>
        )}

        {importMut.data && (
          <div className="small text-secondary mb-2">
            ✓ imported {importMut.data.imported}, matched {importMut.data.matched} to hats
          </div>
        )}
        {rematchMut.data && (
          <div className="small text-secondary mb-2">
            ✓ matched {rematchMut.data.matched}, {rematchMut.data.unmatched} still unmatched
          </div>
        )}
        {unmatchMut.data && (
          <div className="small text-secondary mb-2">
            ✓ unlinked {unmatchMut.data.unmatched}, cleared {unmatchMut.data.fields_cleared} fields
          </div>
        )}
        {(previewMut.error || importMut.error) && (
          <div className="alert alert-danger mt-3 mb-3 small">
            {String(previewMut.error || importMut.error)}
          </div>
        )}

        {rows.slice(0, 8).map(r => (
          <div key={r.id} className="small d-flex justify-content-between gap-2 mb-1">
            <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {r.hat_id != null ? '🔗 ' : '· '}{r.item_title}
            </span>
            <span className="font-mono text-secondary">
              {r.price != null ? `$${r.price.toFixed(2)}` : '—'}
            </span>
          </div>
        ))}
        {rows.length > 8 && <div className="small text-muted">…and {rows.length - 8} more</div>}
      </div>
    </div>
  );
}
