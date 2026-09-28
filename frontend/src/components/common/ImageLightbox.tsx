import { useCallback, useRef, useState } from 'react';
import { useDialogKeys } from './Modal';
import { portalToBody } from './ModalPortal';

interface Props {
  src: string;
  alt?: string;
  /** When true, render a square photo with the synthwave canvas backdrop. */
  hat?: boolean;
}

/**
 * A photo that opens full-screen on tap.
 *
 * The thumbnail is a real `<button>` — a bare `<img onClick>` was invisible
 * to the keyboard and read to a screen reader as a picture, not a control —
 * and the overlay is a dialog that Escape closes, which the close button
 * alone did not give anyone who cannot reach it.
 */
export function ImageLightbox({ src, alt = '', hat = false }: Props) {
  const [open, setOpen] = useState(false);
  const overlayRef = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  // Escape closes, focus moves onto the close button and comes back to the
  // thumbnail afterwards, Tab cannot leave the overlay — the same contract
  // every other dialog here honors.
  useDialogKeys(open, close, overlayRef);

  return (
    <>
      <button
        type="button"
        className={`hr-lightbox-trigger${hat ? ' is-hat' : ''}`}
        aria-label={alt ? `View ${alt} full size` : 'View photo full size'}
        onClick={() => setOpen(true)}
      >
        <img
          src={src}
          alt={alt}
          className={hat ? 'hr-hat-photo hr-lightbox-thumb' : 'rounded hr-lightbox-thumb'}
        />
        {/* A touch screen has no hover to hint that the photo opens, so the
            corner mark says it — quietly, until the photo is pointed at. */}
        <span className="hr-lightbox-hint" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" focusable="false">
            <path d="M15 3h6v6" /><path d="M9 21H3v-6" /><path d="M21 3l-7 7" /><path d="M3 21l7-7" />
          </svg>
        </span>
      </button>
      {/* Portalled: rendered in place, `position: fixed` is measured against
          any ancestor with a transform — and the settings panels and card
          hovers both use one — so the "full screen" overlay could open
          confined to a card. See `ModalPortal`. */}
      {open && portalToBody(
        <div
          className="hr-lightbox-overlay"
          role="dialog"
          aria-modal="true"
          aria-label={alt || 'Photo'}
          onClick={() => setOpen(false)}
          ref={overlayRef}
        >
          <button
            className="hr-lightbox-close"
            onClick={e => { e.stopPropagation(); setOpen(false); }}
            aria-label="Close"
          >
            ×
          </button>
          <img
            src={src}
            alt={alt}
            className="hr-lightbox-content"
            onClick={e => e.stopPropagation()}
          />
        </div>,
      )}
    </>
  );
}
