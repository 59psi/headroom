import { useEffect, useId, useRef } from 'react';
import type { ReactNode } from 'react';
import { portalToBody } from './ModalPortal';

/**
 * What a dialog owes the keyboard, in one place.
 *
 * Escape closes it, focus moves into it when it opens and goes back to
 * whatever opened it when it closes, and Tab stays inside it. The lightbox
 * had Escape and the four form modals (dispose, new case, color, cropper)
 * had none of this — each was a `<div className="modal">` with no role, so a
 * screen reader read the page behind it and the keyboard could leave it.
 *
 * Bound to the DOCUMENT, not the dialog: the cropper's focus sits inside a
 * third-party canvas, and a key handler on the dialog element never hears
 * a key pressed there.
 */
export function useDialogKeys(open: boolean, onClose: () => void, dialogRef: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    // Initial focus: the first control, else the dialog itself.
    const first = dialog?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? dialog)?.focus();

    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== 'Tab' || !dialog) return;
      const items = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE))
        .filter(el => !el.hasAttribute('disabled') && el.tabIndex !== -1);
      if (items.length === 0) return;
      const firstItem = items[0];
      const lastItem = items[items.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === firstItem || !dialog.contains(active))) {
        e.preventDefault();
        lastItem.focus();
      } else if (!e.shiftKey && active === lastItem) {
        e.preventDefault();
        firstItem.focus();
      }
    }
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      // Back to the button that opened it — otherwise focus lands on <body>
      // and a keyboard user starts the page over from the top.
      opener?.focus?.();
    };
  }, [open, onClose, dialogRef]);
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
  'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

interface ModalProps {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  /** `max-width` of the dialog box; the stylesheet's default otherwise. */
  maxWidth?: number;
  /** Class for the body wrapper; the cropper zeroes its padding. */
  bodyStyle?: React.CSSProperties;
}

/**
 * The one modal shell. Renders into `<body>` (see `ModalPortal`), carries
 * the dialog role and labelling, and delegates the keyboard to
 * `useDialogKeys`. A click on the backdrop closes; a click inside does not.
 */
export function Modal({ title, onClose, children, footer, maxWidth, bodyStyle }: ModalProps) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  useDialogKeys(true, onClose, dialogRef);

  return portalToBody(
    <div className="modal" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div
        className="modal-dialog"
        style={maxWidth ? { maxWidth } : undefined}
        onClick={e => e.stopPropagation()}
      >
        <div
          className="modal-content"
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          tabIndex={-1}
          ref={dialogRef}
        >
          <div className="modal-header">
            <h5 className="modal-title" id={titleId}>{title}</h5>
            <button type="button" className="btn-close" onClick={onClose} aria-label="Close" />
          </div>
          <div className="modal-body" style={bodyStyle}>{children}</div>
          {footer && <div className="modal-footer">{footer}</div>}
        </div>
      </div>
    </div>,
  );
}
