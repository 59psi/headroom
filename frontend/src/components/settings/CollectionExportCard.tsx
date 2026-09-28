import { useState } from 'react';
import { collectionExportUrl } from '../../api/settings';
import { Panel } from '../ui/Panel';
import { useToast } from '../ui/Toast';

/**
 * Download the collection as a zip you can hand to someone.
 *
 * Distinct from the Inventory report beside it, and the copy has to say how:
 * that one is a valuation table for an insurer, this one is the version you
 * send a friend. They differ mainly in whether the money is in it, which is
 * not a difference anyone will guess from two buttons sitting side by side —
 * so the one-line description says it, and the details wait in the help.
 */
export function CollectionExportCard() {
  const toast = useToast();
  const [title, setTitle] = useState('The Collection');
  const [includeValues, setIncludeValues] = useState(false);
  const [includeDisposed, setIncludeDisposed] = useState(false);

  return (
    <Panel
      title="Share the collection"
      className="hr-sharing"
      description="A .zip anyone can open in a browser — offline, no login, no prices unless you add them."
      help={
        <>
          <p>
            Open <code>index.html</code> inside the <strong>.zip</strong> in any
            browser. Works offline, no login, nothing to host. Every hat gets its
            photo, colors, and its write-up. It is a snapshot of the moment you
            download it.
          </p>
          <p>
            A share link is better when the person can reach this app: it stays
            current and you can revoke it. Use this when they can&rsquo;t. For a
            valuation with the money in it, use the Inventory report.
          </p>
        </>
      }
      footer={
        // An anchor, not a fetch: the browser handles the filename from
        // Content-Disposition and shows its own progress, which beats
        // buffering several MB into a blob URL to achieve the same thing.
        //
        // But the server builds the whole zip BEFORE the first byte goes out
        // (photos included — seconds on a Pi), and until then the browser shows
        // nothing at all, so the button reads as dead and gets pressed again.
        // The toast covers that gap without taking the download away from the
        // browser.
        <a
          className="btn btn-primary"
          href={collectionExportUrl({
            title: title.trim() || undefined,
            includeValues,
            includeDisposed,
          })}
          onClick={() => toast.info('Building the .zip — the download starts when it’s ready.')}
        >
          Download .zip
        </a>
      }
    >
      <label className="form-label" htmlFor="export-title">Title</label>
      <input
        id="export-title"
        aria-label="Export title"
        className="form-control mb-3"
        value={title}
        maxLength={80}
        onChange={e => setTitle(e.target.value)}
      />

      <div className="hr-export-options">
        <div className="form-check">
          <input
            className="form-check-input"
            type="checkbox"
            id="export-values"
            checked={includeValues}
            onChange={e => setIncludeValues(e.target.checked)}
          />
          <label className="form-check-label" htmlFor="export-values">
            Include estimated values <span className="text-muted">— off by default</span>
          </label>
        </div>
        <div className="form-check">
          <input
            className="form-check-input"
            type="checkbox"
            id="export-disposed"
            checked={includeDisposed}
            onChange={e => setIncludeDisposed(e.target.checked)}
          />
          <label className="form-check-label" htmlFor="export-disposed">
            Include hats you no longer own
          </label>
        </div>
      </div>
    </Panel>
  );
}
