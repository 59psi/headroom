import { useId, type ReactNode } from 'react';

/**
 * The one card shell for anything that is a titled block of controls —
 * every Settings card, and the titled sections of the detail pages.
 *
 * Each settings card used to hand-roll the same markup with a different idea
 * of where things go: the status was a sentence somewhere in the body, the
 * explanation was a paragraph as long as the controls under it, and the
 * primary button floated wherever the last field ended. The shell fixes the
 * order so a person learns it once:
 *
 *   title ··················· status · actions
 *   one-line description
 *   ▸ How this works               (optional; the long explanation)
 *   body
 *   footer                         (the card's primary action row)
 *
 * The long explanation is still there — much of it is the only documentation
 * a self-hosted app has — it is just folded away behind a disclosure instead
 * of standing between the reader and the button they came for.
 */
export interface PanelProps {
  title: ReactNode;
  /** A `StatusPill` (or anything small) at the right of the title. */
  status?: ReactNode;
  /** Small controls beside the status: refresh, overflow. */
  actions?: ReactNode;
  /** One sentence under the title. */
  description?: ReactNode;
  /** The long explanation, collapsed behind a disclosure. */
  help?: ReactNode;
  /** Disclosure label for `help`. */
  helpLabel?: string;
  /** The card's primary action row, pinned under the body. */
  footer?: ReactNode;
  /** Sunset stripe across the top — the one card a section is built around. */
  featured?: boolean;
  /** Heading level. Settings cards sit under the page's h1, so h2. */
  as?: 'h2' | 'h3';
  className?: string;
  id?: string;
  children?: ReactNode;
}

export function Panel({
  title, status, actions, description, help, helpLabel = 'How this works', footer,
  featured = false, as: Heading = 'h2', className = '', id, children,
}: PanelProps) {
  const titleId = useId();
  return (
    <section
      id={id}
      className={`card hr-panel${featured ? ' hr-feature' : ''}${className ? ` ${className}` : ''}`}
      aria-labelledby={titleId}
    >
      <div className="card-body">
        <header className="hr-panel-head">
          <div className="hr-panel-heading">
            <Heading className="card-title hr-panel-title" id={titleId}>{title}</Heading>
            {description && <p className="hr-panel-desc">{description}</p>}
          </div>
          {(status || actions) && (
            <div className="hr-panel-aside">
              {status}
              {actions}
            </div>
          )}
        </header>
        {help && (
          <details className="hr-panel-help">
            <summary>{helpLabel}</summary>
            <div className="hr-panel-help-body">{help}</div>
          </details>
        )}
        {children !== undefined && children !== null && children !== false && (
          <div className="hr-panel-body">{children}</div>
        )}
        {footer && <div className="hr-panel-foot">{footer}</div>}
      </div>
    </section>
  );
}
