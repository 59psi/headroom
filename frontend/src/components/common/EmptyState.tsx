import { Link } from 'react-router-dom';

interface Props {
  title: string;
  message: string;
  actionLabel?: string;
  actionTo?: string;
}

export function EmptyState({ title, message, actionLabel, actionTo }: Props) {
  return (
    <div className="text-center py-5">
      <div className="mb-3" style={{ color: 'var(--neon-purple)', opacity: 0.6 }}>
        <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <rect x="2" y="7" width="20" height="14" rx="2"/>
          <path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/>
          <line x1="12" y1="12" x2="12" y2="16"/>
          <line x1="10" y1="14" x2="14" y2="14"/>
        </svg>
      </div>
      <h5 className="mb-2" style={{ color: 'var(--text)' }}>{title}</h5>
      <p className="text-secondary small mb-3">{message}</p>
      {actionLabel && actionTo && (
        <Link to={actionTo} className="btn btn-primary">{actionLabel}</Link>
      )}
    </div>
  );
}
