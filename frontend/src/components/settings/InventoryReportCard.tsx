import { inventoryReportUrl } from '../../api/settings';
import { Panel } from '../ui/Panel';
import { StatusPill } from '../ui/StatusPill';

/**
 * The valuation table — the version with the money in it (the zip in "Share
 * the collection" is the one without). Two variants, each still one tap as
 * they were before the card moved onto `Panel`: the hats you own, or those
 * plus the ones you have disposed of. The second stays a separate link
 * rather than becoming a checkbox in front of one button, which would have
 * made the less common report cost two taps for no gain in clarity.
 */
export function InventoryReportCard() {
  return (
    <Panel
      title="Inventory report"
      className="hr-sharing"
      // Built fresh on every open, so there is no stale state to report —
      // what the word can usefully say is what is IN it, beside the export
      // card's "No prices".
      status={<StatusPill tone="info" title="Every report carries current values">With values</StatusPill>}
      description="A print-friendly valuation of every hat you own — open it, then Print → Save as PDF."
      help={
        <p>
          Print-friendly HTML — use your browser&rsquo;s <strong>Print → Save as
          PDF</strong> to export. Includes thumbnails, totals, brand / model,
          condition, location, and best-available current value for every hat.
          Opens in a new tab.
        </p>
      }
      footer={
        <>
          <a href={inventoryReportUrl()} target="_blank" rel="noopener noreferrer" className="btn btn-primary">
            Open report
          </a>
          <a
            href={inventoryReportUrl({ includeDisposed: true })}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-outline-secondary"
          >
            Open with disposed hats
          </a>
        </>
      }
    />
  );
}
