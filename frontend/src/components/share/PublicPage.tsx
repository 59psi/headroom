import { useState, type ReactNode } from 'react';
import { PUBLIC_LOGO_URL } from '../../api/public';

/**
 * The frame for every page an outside viewer can reach — the guest
 * collection, a guest's hat page, a share link.
 *
 * Those pages sit outside the app shell (a visitor has no session, so every
 * nav tab would bounce them to the login screen), and each used to build its
 * own frame out of inline styles: a bare "HEADROOM" h1 on the error states, no
 * brand at all once the page loaded, and a different width per page. So a
 * visitor saw three products. One frame puts the brand in a header bar that
 * stays put while the grid scrolls, which also frees the page's own heading to
 * say what the page IS — "The collection", the hat, the link's label.
 */
export function PublicPage({
  action,
  narrow = false,
  children,
}: {
  /** One control at the right of the header bar ("Sign in"). */
  action?: ReactNode;
  /** A single-item page (a hat) reads better at a column's width than at a grid's. */
  narrow?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="hr-public">
      <header className="hr-public-bar">
        <PublicBrand />
        {action && <div className="hr-public-action">{action}</div>}
      </header>
      <main className={`hr-public-main${narrow ? ' is-narrow' : ''}`}>{children}</main>
    </div>
  );
}

/**
 * Logo and wordmark. The logo comes from the unauthenticated branding route —
 * the same one the login screen uses — and drops out on its own when the
 * owner has not uploaded one, so the wordmark stands alone rather than beside
 * a broken-image box.
 */
export function PublicBrand() {
  const [logoOk, setLogoOk] = useState(true);
  return (
    <span className="hr-public-brand">
      {logoOk && (
        <img src={PUBLIC_LOGO_URL} alt="" onError={() => setLogoOk(false)} />
      )}
      <span className="hr-wordmark">Headroom</span>
    </span>
  );
}

/**
 * The page in place of content that could not be shown: a link that was
 * revoked, guest browsing switched off, a hat that is gone.
 *
 * The title carries the message itself, not the brand — the header bar
 * already says where you are, and "HEADROOM" in 40px over one line of gray
 * text made the brand the loudest thing on a page whose only job is to say
 * what went wrong.
 */
export function PublicNotice({
  title,
  detail,
  action,
}: {
  title: ReactNode;
  detail?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="hr-public-notice">
      <CapGlyph className="hr-public-notice-icon" />
      <h1 className="hr-public-notice-title">{title}</h1>
      {detail && <p className="hr-public-notice-detail">{detail}</p>}
      {action && <div className="hr-public-notice-action">{action}</div>}
    </div>
  );
}

/**
 * The cap outline the bottom nav uses for Hats, drawn where a hat has no
 * photo. It replaced a 🧢 emoji, which rendered as a different cartoon on
 * every platform and was the one full-color object on an otherwise neon
 * page.
 */
export function CapGlyph({ className = '' }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M12 2C6.5 2 2 6 2 10c0 2 1 4 3 5v3h14v-3c2-1 3-3 3-5 0-4-4.5-8-10-8z" />
      <path d="M2 15h20" />
    </svg>
  );
}
