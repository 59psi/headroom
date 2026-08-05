/** Static how-to: Android PWA share target + the equivalent iOS Shortcut recipe. */
export function ShareTargetCard() {
  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Share Photos to Headroom</div>
        <p className="text-secondary small mb-3">
          <strong>Android Chrome:</strong> install Headroom as a PWA (browser
          menu → Install app), then "Share to Headroom" appears in the system
          share sheet automatically — selected photos route into a bulk-import
          job.
        </p>
        <p className="text-secondary small mb-3">
          <strong>iOS Safari</strong> doesn't support Web Share Target yet,
          so use a one-time Shortcut. Open the Shortcuts app → tap <strong>+</strong>
          → add these actions in order:
        </p>
        <ol className="text-secondary small mb-3" style={{ paddingLeft: '1.2rem' }}>
          <li className="mb-1"><strong>Receive</strong> Images from Share Sheet (toggle "Show in Share Sheet" ON)</li>
          <li className="mb-1"><strong>Get Contents of URL</strong>
            <ul style={{ paddingLeft: '1.2rem', marginTop: '0.25rem' }}>
              <li>URL: <code style={{ fontSize: '0.85em' }}>{`${window.location.origin}/api/hats/import`}</code></li>
              <li>Method: <code>POST</code></li>
              <li>Headers → add: key=<code>Authorization</code>, value=<code>Bearer YOUR-API-TOKEN</code> (copy the token from the <strong>Account</strong> card below)</li>
              <li>Request Body: <code>Form</code></li>
              <li>Add field: key=<code>photos</code>, type=<code>File</code>, value=<em>Shortcut Input</em></li>
            </ul>
          </li>
          <li>Name it "Add to Headroom" and you're done.</li>
        </ol>
        <p className="text-muted small mb-0" style={{ fontSize: '0.75rem' }}>
          Now open Photos → select multiple → Share → "Add to Headroom".
          Each shared photo becomes a hat with the same defaults the Bulk Import
          page uses (style: A-Game · size: classic · condition: new) — edit
          after Claude finishes analyzing.
        </p>
      </div>
    </div>
  );
}
