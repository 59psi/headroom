/**
 * Credit, version and the one outbound link, set small and quiet: nobody
 * comes to the bottom of a page for the footer, but "which build is this
 * box running" is a question it has to answer when asked.
 */
export function Footer() {
  return (
    <footer className="hr-footer">
      <p className="hr-footer-line">&copy; 2026 Brandon Bianchi · Made with neon</p>
      <p className="hr-footer-line hr-footer-meta">
        <span className="hr-footer-version">
          v{__APP_VERSION__}
          {__BUILD_SHA__ && ` · build ${__BUILD_SHA__}`}
        </span>
        <span aria-hidden="true">·</span>
        <a
          href="https://github.com/59psi/headroom/tree/main/hardware"
          target="_blank"
          rel="noreferrer"
        >
          3D-print the case rack
        </a>
      </p>
    </footer>
  );
}
