import { formatDateOnly } from '../../lib/dates';
import { money } from '../../lib/valuation';
import type { LinkedHat, PurchaseRead, SuspectReason } from '../../types';

/** One receipt line, as the dialogs and lists headline it: date · price · size. */
export function receiptLine(p: PurchaseRead, sizeLabel: (v: string) => string): string {
  return [
    p.order_date && formatDateOnly(p.order_date),
    p.price != null && money(p.price),
    p.size && sizeLabel(p.size),
    p.order_ref && `order ${p.order_ref}`,
  ].filter(Boolean).join(' · ');
}

type Why = (p: PurchaseRead, hat: LinkedHat, sizeLabel: (v: string) => string) => string;

/** One sentence per rule the matcher can rule a hat out by. A `Record`, so a
 *  new `SuspectReason` does not compile until it has its sentence. */
const WHY: Record<SuspectReason, Why> = {
  model: (p, hat) => (p.model_name && hat.model_name
    ? `The receipt is for “${p.model_name}”, and this hat is “${hat.model_name}”.`
    : 'The receipt’s model is not this hat’s.'),
  construction: (_p, hat) =>
    `The hat is recorded as ${hat.construction ?? 'another construction'}, and the receipt names a different one.`,
  series: (_p, hat) => `“${hat.artist_series ?? 'Its series'}” is nowhere on the receipt.`,
  colorway: (p, hat) => `The receipt says “${p.colorway}”, and the hat says “${hat.colorway}”.`,
  size: (p, hat, sizeLabel) =>
    `The receipt says ${p.size ? sizeLabel(p.size) : 'one size'}, and the hat says ${hat.size ? sizeLabel(hat.size) : 'another'}.`,
};

/**
 * Why a suspect link is flagged, named by the field that disagrees — the
 * matcher's own veto (`suspect_reason`). Both the review list and the hat
 * page used to say the hat's series was missing from the receipt for every
 * one, including links a different model or size had ruled out.
 */
export function suspectWhy(p: PurchaseRead, sizeLabel: (v: string) => string): string | null {
  if (!p.suspect || !p.hat || !p.suspect_reason) return null;
  return WHY[p.suspect_reason](p, p.hat, sizeLabel);
}
