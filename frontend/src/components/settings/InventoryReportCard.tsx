import { inventoryReportUrl } from '../../api/settings';

export function InventoryReportCard() {
  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Inventory Report</div>
        <p className="text-secondary small mb-3">
          Print-friendly HTML — use your browser's <strong>Print → Save as PDF</strong>
          to export. Includes thumbnails, totals, brand / model, condition, location,
          and best-available current value for every hat.
        </p>
        <div className="d-flex gap-2 flex-wrap">
          <a href={inventoryReportUrl()} target="_blank" rel="noopener noreferrer" className="btn btn-primary">
            Open Report (active hats)
          </a>
          <a href={inventoryReportUrl({ includeDisposed: true })} target="_blank" rel="noopener noreferrer" className="btn btn-outline-primary">
            Include Disposed
          </a>
        </div>
      </div>
    </div>
  );
}
