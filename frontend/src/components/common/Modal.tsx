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
 *
 * Only the TOPMOST open dialog answers. Dialogs can stack now — "Remove this
 * color?" opens over the color editor — and every open one has a document
 * listener, so a single Escape closed both, and Tab from the inner dialog was
 * pulled back into the outer one by the outer's trap.
 */
const openDialogs: object[] = [];

export function useDialogKeys(open: boolean, onClose: () => void, dialogRef: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!open) return;
    const token = {};
    openDialogs.push(token);
    const opener = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    // Initial focus: a control that asked for it (`data-autofocus` — the text
    // field of a prompt, the safe button of a destructive confirm), else the
    // first control, else the dialog itself. Without the opt-in the first
    // control is always the header's close button.
    const preferred = dialog?.querySelector<HTMLElement>('[data-autofocus]');
    const first = dialog?.querySelector<HTMLElement>(FOCUSABLE);
    (preferred ?? first ?? dialog)?.focus();

    function onKey(e: KeyboardEvent) {
      if (openDialogs[openDialogs.length - 1] !== token) return;
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
      const outside = !dialog.contains(active);
      if (e.shiftKey && (active === firstItem || outside)) {
        e.preventDefault();
        lastItem.focus();
      } else if (!e.shiftKey && (active === lastItem || outside)) {
        e.preventDefault();
        firstItem.focus();
      }
    }
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      const at = openDialogs.indexOf(token);
      if (at !== -1) openDialogs.splice(at, 1);
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
  /**
   * The body is the dialog's DESCRIPTION (`aria-describedby`), read out with
   * the title when it opens. For short message dialogs — a confirm's "its
   * hats become unassigned" — not for forms, where the body is the controls.
   */
  describeBody?: boolean;
  /**
   * `alertdialog`: an interruption that demands a decision (a destructive
   * confirm), announced more urgently than a plain dialog.
   */
  alert?: boolean;
}

/**
 * The one modal shell. Renders into `<body>` (see `ModalPortal`), carries
 * the dialog role and labelling, and delegates the keyboard to
 * `useDialogKeys`. A click on the backdrop closes; a click inside does not.
 */
export function Modal({
  title, onClose, children, footer, maxWidth, bodyStyle, describeBody = false, alert = false,
}: ModalProps) {
  const titleId = useId();
  const bodyId = useId();
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
          role={alert ? 'alertdialog' : 'dialog'}
          aria-modal="true"
          aria-labelledby={titleId}
          aria-describedby={describeBody ? bodyId : undefined}
          tabIndex={-1}
          ref={dialogRef}
        >
          <div className="modal-header">
            <h5 className="modal-title" id={titleId}>{title}</h5>
            <button type="button" className="btn-close" onClick={onClose} aria-label="Close" />
          </div>
          <div className="modal-body" id={bodyId} style={bodyStyle}>{children}</div>
          {footer && <div className="modal-footer">{footer}</div>}
        </div>
      </div>
    </div>,
  );
}
