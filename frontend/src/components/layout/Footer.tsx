export function Footer() {
  return (
    <footer className="hr-footer">
      <div>&copy; 2026 BRANDON BIANCHI · MADE WITH NEON</div>
      <div style={{ marginTop: 4, opacity: 0.7, fontSize: '0.7rem' }}>
        v{__APP_VERSION__}
        {__BUILD_SHA__ && ` · build ${__BUILD_SHA__}`} ·{' '}
        <a
          href="https://github.com/59psi/headroom/tree/main/hardware"
          target="_blank"
          rel="noreferrer"
        >
          3D-PRINT THE CASE RACK
        </a>
      </div>
    </footer>
  );
}
