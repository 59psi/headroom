import { useState } from 'react';
import { collectionExportUrl } from '../../api/settings';

/**
 * Download the collection as a zip you can hand to someone.
 *
 * Distinct from the Inventory Report above it, and the copy has to say how:
 * that one is a valuation table for an insurer, this one is the version you
 * send a friend. They differ mainly in whether the money is in it, which is
 * not a difference anyone will guess from two buttons sitting side by side.
 */
export function CollectionExportCard() {
  const [title, setTitle] = useState('The Collection');
  const [includeValues, setIncludeValues] = useState(false);
  const [includeDisposed, setIncludeDisposed] = useState(false);

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Share the collection</div>
        <p className="text-secondary small mb-3">
          Downloads a <strong>.zip</strong> — open <code>index.html</code> inside it in
          any browser. Works offline, no login, nothing to host. Every hat gets its
          photo, colors, and its write-up.
          <br />
          <span className="text-muted">
            A share link is better when the person can reach this app: it stays current
            and you can revoke it. Use this when they can&rsquo;t.
          </span>
        </p>

        <label className="form-label" style={{ fontSize: '0.8rem' }} htmlFor="export-title">
          Title
        </label>
        <input
          id="export-title"
          aria-label="Export title"
          className="form-control mb-3"
          value={title}
          maxLength={80}
          onChange={e => setTitle(e.target.value)}
        />

        <div className="form-check mb-1">
          <input
            className="form-check-input"
            type="checkbox"
            id="export-values"
            checked={includeValues}
            onChange={e => setIncludeValues(e.target.checked)}
          />
          <label className="form-check-label small" htmlFor="export-values">
            Include estimated values <span className="text-muted">— off by default</span>
          </label>
        </div>
        <div className="form-check mb-3">
          <input
            className="form-check-input"
            type="checkbox"
            id="export-disposed"
            checked={includeDisposed}
            onChange={e => setIncludeDisposed(e.target.checked)}
          />
          <label className="form-check-label small" htmlFor="export-disposed">
            Include hats you no longer own
          </label>
        </div>

        {/* An anchor, not a fetch: the browser handles the filename from
            Content-Disposition and shows its own progress, which beats
            buffering several MB into a blob URL to achieve the same thing. */}
        <a
          className="btn btn-primary"
          href={collectionExportUrl({
            title: title.trim() || undefined,
            includeValues,
            includeDisposed,
          })}
        >
          Download .zip
        </a>
      </div>
    </div>
  );
}
