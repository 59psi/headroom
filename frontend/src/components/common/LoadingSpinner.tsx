export function LoadingSpinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="d-flex flex-column align-items-center justify-content-center py-5 gap-3">
      <div className="spinner-border" role="status">
        <span className="visually-hidden">{label}…</span>
      </div>
      <div className="text-secondary small font-mono" style={{ letterSpacing: '0.16em', textTransform: 'uppercase' }}>
        {label}…
      </div>
    </div>
  );
}
