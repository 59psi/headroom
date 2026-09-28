import { useRef, useState } from 'react';
import { Link } from 'react-router';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  importPurchases, listPurchases, previewImport, rematchPurchases, unmatchAllPurchases,
  unmatchPurchase,
} from '../../api/purchases';
import type { ImportPreview, PurchaseRead } from '../../types';
import { plural } from '../../lib/format';
import { invalidateHatViews, invalidatePurchaseDerived } from '../../lib/invalidate';
import { qk } from '../../lib/queryKeys';
import { ErrorNote } from '../common/ErrorNote';
import { CopyButton } from '../ui/CopyButton';
import { Panel } from '../ui/Panel';
import { StatusPill } from '../ui/StatusPill';
import { Skeleton } from '../ui/Skeleton';
import { useToast } from '../ui/Toast';
import { useConfirm } from '../ui/Dialogs';

const KEY = qk.admin.purchases();

/** How many purchase rows to list inline; the rest are counted, not hidden. */
const ROW_LIMIT = 8;

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
 *  card are not the one time you set up the import. The prompt is on screen
 *  and selectable either way, so a refused clipboard costs the convenience,
 *  not the feature — and `CopyButton` says so rather than doing nothing. */
function EmailPromptDisclosure() {
  return (
    <details className="hr-prompt-details hr-sd-disclosure">
      <summary className="text-secondary small">
        No JSON yet? Get one from your email
      </summary>
      <div className="mt-2">
        <p className="text-secondary small mb-2">
          Paste this into Claude or ChatGPT with access to your mail. It reads your
          melin receipts and returns the JSON this card imports.
        </p>
        <CopyButton text={EMAIL_IMPORT_PROMPT} what="import prompt" className="mb-2" />
        <pre className="hr-prompt-text font-mono">{EMAIL_IMPORT_PROMPT}</pre>
      </div>
    </details>
  );
}

export function PurchasesCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const fileRef = useRef<HTMLInputElement>(null);
  // The parsed file is held here until it is either imported or discarded.
  // Re-reading it on confirm would mean the preview and the import could see
  // two different files if the picker were touched in between.
  const [staged, setStaged] = useState<{ name: string; items: Record<string, unknown>[] } | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [readError, setReadError] = useState<string | null>(null);

  const purchases = useQuery({
    queryKey: KEY,
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

  // Outcomes are toasts; the tiles above are the lasting record. Each of these
  // used to leave a "✓ imported 12, matched 9" line behind that sat on the
  // card, beside tiles that already said the same thing, until a reload.
  // `invalidatePurchaseDerived` covers this card's own list as well as the
  // keys matching feeds on other cards; the hats it wrote onto are the rest.
  const importMut = useMutation({
    mutationFn: importPurchases,
    onSuccess: result => {
      toast.success(`Imported ${result.imported}, matched ${result.matched} to hats`);
      invalidatePurchaseDerived(qc);
      void invalidateHatViews(qc);
      reset();
    },
  });

  const rematchMut = useMutation({
    mutationFn: rematchPurchases,
    onSuccess: result => {
      toast.success(`Matched ${result.matched}, ${result.unmatched} still unmatched`);
      invalidatePurchaseDerived(qc);
      void invalidateHatViews(qc);
    },
  });

  const unmatchMut = useMutation({
    mutationFn: unmatchAllPurchases,
    onSuccess: result => {
      toast.success(
        `Unlinked ${result.unmatched}, cleared ${plural(result.fields_cleared, 'field')}`,
      );
      invalidatePurchaseDerived(qc);
      void invalidateHatViews(qc);
    },
  });

  // One row at a time — the undo a single wrong link needs. `unmatch-all`
  // was the only undo the card offered, so fixing one row meant unlinking
  // every purchase and re-running the matcher over the whole collection.
  //
  // Optimistic: the row drops its link the instant it is pressed. The server's
  // answer is predictable (it unlinks exactly that purchase), and a failure
  // restores the cached list. The hat id is captured BEFORE the optimistic
  // write, because afterwards the cache no longer knows which hat it was.
  const unmatchOneMut = useMutation({
    mutationFn: unmatchPurchase,
    onMutate: async (purchaseId: number) => {
      await qc.cancelQueries({ queryKey: KEY });
      const previous = qc.getQueryData<PurchaseRead[]>(KEY);
      const hatId = previous?.find(r => r.id === purchaseId)?.hat_id ?? undefined;
      qc.setQueryData<PurchaseRead[]>(KEY, list =>
        list?.map(r => (r.id === purchaseId ? { ...r, hat_id: null } : r)));
      return { previous, hatId };
    },
    onError: (_err, _id, ctx) => {
      if (ctx?.previous) qc.setQueryData(KEY, ctx.previous);
    },
    onSuccess: (result, _id, ctx) => {
      toast.success('Purchase unlinked');
      void invalidateHatViews(qc, result.hat_id ?? ctx?.hatId);
    },
    // The list refetch on failure too — the rollback restored a snapshot —
    // and with it everything else matching feeds.
    onSettled: () => {
      invalidatePurchaseDerived(qc);
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

  // Unlinking everything reverts what matching wrote onto every linked hat,
  // and the matcher is the only way back — so it asks first, in-app. It used
  // to fire on the first tap, one button along from "Re-run matching".
  //
  // The body is a plain string on purpose: outside a DialogProvider `confirm`
  // falls back to `window.confirm`, which can only carry text — markup there
  // is dropped, and the question would be asked without its consequences.
  const unlinkAll = async () => {
    const ok = await confirm({
      title: 'Unlink every purchase?',
      body:
        'Every purchase is unlinked from its hat, and the colorway, cost basis and '
        + 'purchase date that matching wrote are cleared — unless you have edited '
        + 'them since. The purchases themselves are kept; “Re-run matching” links '
        + 'them again.',
      confirmLabel: 'Unlink all',
      tone: 'danger',
    });
    if (ok) unmatchMut.mutate();
  };

  const rows = purchases.data ?? [];
  const linked = rows.filter(r => r.hat_id != null).length;
  const unlinked = rows.length - linked;
  const busy = previewMut.isPending || importMut.isPending;
  // The one primary action per card: picking a file, until a preview is up —
  // then confirming that preview is the thing to do, and picking another file
  // steps back to secondary.
  const reviewing = !!(staged && preview);

  return (
    <Panel
      title="Purchase history"
      status={purchases.isSuccess && (
        rows.length === 0
          ? <StatusPill tone="off">None imported</StatusPill>
          : unlinked === 0
            ? <StatusPill tone="ok">All linked</StatusPill>
            : <StatusPill tone="info">{unlinked} unlinked</StatusPill>
      )}
      description="Order lines from your melin receipts. Matching gives hats their colorway and what you paid, so valuation shows a real gain."
      help={
        <>
          <p>
            Order line items from your Melin order emails. Matching sets a
            hat&rsquo;s colorway and cost basis — what you actually paid — so the
            valuation can show a real gain rather than a guess.
          </p>
          <p>
            Import a JSON array of line items — each needs <code>item_title</code>,
            and may carry <code>order_ref</code>, <code>order_date</code>,{' '}
            <code>price</code>, <code>quantity</code> and <code>size</code>. Nothing
            is written until you confirm the preview.
          </p>
          <p>
            Importing re-runs matching over every unmatched purchase, not just the
            new file&rsquo;s. <em>Unlink</em> on a row undoes one match;{' '}
            <em>Unlink all</em> undoes them all.
          </p>
        </>
      }
      footer={
        <>
          <button
            type="button"
            className={`btn ${reviewing ? 'btn-outline-secondary' : 'btn-primary'}`}
            onClick={() => fileRef.current?.click()}
            disabled={busy}
          >
            Import JSON…
          </button>
          {rows.length > 0 && (
            <button
              type="button"
              className="btn btn-outline-secondary"
              onClick={() => rematchMut.mutate()}
              disabled={rematchMut.isPending}
            >
              {rematchMut.isPending ? 'Matching…' : 'Re-run matching'}
            </button>
          )}
          {linked > 0 && (
            <button
              type="button"
              className="btn btn-outline-danger"
              onClick={unlinkAll}
              disabled={unmatchMut.isPending}
            >
              {unmatchMut.isPending ? 'Unlinking…' : 'Unlink all'}
            </button>
          )}
        </>
      }
    >
      <input
        ref={fileRef}
        type="file"
        aria-label="Purchase history JSON file"
        accept="application/json,.json"
        onChange={handleFile}
        hidden
      />

      {purchases.isLoading ? (
        <Skeleton height={72} />
      ) : (
        purchases.isSuccess && (
          <dl className="hr-metric-grid hr-sd-metrics">
            <div className="hr-metric">
              <dt className="hr-metric-label">Purchases</dt>
              <dd className="hr-metric-value">{rows.length}</dd>
            </div>
            <div className="hr-metric">
              <dt className="hr-metric-label">Linked to hats</dt>
              <dd className="hr-metric-value">{linked}</dd>
            </div>
          </dl>
        )
      )}

      {readError && <div className="alert alert-danger mt-3 mb-0 small" role="alert">{readError}</div>}

      {previewMut.isPending && (
        <p className="text-secondary small mt-3 mb-0" role="status">Checking that file…</p>
      )}

      {staged && preview && (
        <div className="hr-sd-preview mt-3" role="region" aria-label="Import preview">
          <div className="text-secondary small mb-1 font-mono hr-sd-filename">{staged.name}</div>
          {preview.would_import === 0 ? (
            <p className="small mb-2">
              Nothing new to import —{' '}
              {preview.duplicates === 1
                ? 'its one line is already on record.'
                : `all ${plural(preview.duplicates, 'line')} are already on record.`}
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
            <p className="small mb-2 hr-sd-warn-text">
              <strong>
                Also matches {plural(preview.would_match_backlog, 'purchase')} already on record.
              </strong>{' '}
              Importing re-runs matching over everything unmatched, so this writes a
              colorway and cost basis onto {plural(preview.would_match_total, 'hat')} in
              total. Unlink all is the only undo.
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

      <ErrorNote
        className="mt-3"
        of={[purchases, previewMut, importMut, rematchMut, unmatchMut, unmatchOneMut]}
      />

      {rows.length > 0 && (
        <>
          <span className="hr-eyebrow mt-3">Recent purchases</span>
          <ul className="hr-sd-rows">
            {rows.slice(0, ROW_LIMIT).map(r => (
              <li key={r.id}>
                <span className="hr-sd-row-title">
                  <span
                    className={`hr-sd-link-dot${r.hat_id != null ? ' is-linked' : ''}`}
                    aria-hidden="true"
                  />
                  <span className="visually-hidden">
                    {r.hat_id != null ? 'Linked: ' : 'Not linked: '}
                  </span>
                  {/* A linked row opens its hat: the link is the thing a
                      person checks before deciding it is wrong. */}
                  <span className="hr-sd-row-text">
                    {r.hat_id != null
                      ? <Link to={`/hats/${r.hat_id}`}>{r.item_title}</Link>
                      : r.item_title}
                  </span>
                </span>
                <span className="hr-sd-row-aside">
                  <span className="font-mono text-secondary">
                    {r.price != null ? `$${r.price.toFixed(2)}` : '—'}
                  </span>
                  {r.hat_id != null && (
                    <button
                      type="button"
                      className="btn btn-outline-secondary btn-sm"
                      aria-label={`Unlink ${r.item_title} from its hat`}
                      disabled={unmatchOneMut.isPending}
                      onClick={() => unmatchOneMut.mutate(r.id)}
                    >
                      Unlink
                    </button>
                  )}
                </span>
              </li>
            ))}
          </ul>
          {rows.length > ROW_LIMIT && (
            <div className="small text-muted mt-1">…and {rows.length - ROW_LIMIT} more</div>
          )}
        </>
      )}

      <hr className="hr-panel-divider" />
      <EmailPromptDisclosure />
    </Panel>
  );
}
