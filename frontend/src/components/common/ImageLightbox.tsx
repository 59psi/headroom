import { useCallback, useRef, useState } from 'react';
import { useDialogKeys } from './Modal';

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
        className="hr-lightbox-trigger"
        aria-label={alt ? `View ${alt} full size` : 'View photo full size'}
        onClick={() => setOpen(true)}
        style={{ maxWidth: hat ? 480 : '100%' }}
      >
        <img
          src={src}
          alt={alt}
          className={hat ? 'hr-hat-photo' : 'rounded'}
          style={{
            width: '100%',
            aspectRatio: hat ? '1' : '4/3',
            objectFit: hat ? 'contain' : 'cover',
            display: 'block',
          }}
        />
      </button>
      {open && (
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
        </div>
      )}
    </>
  );
}
