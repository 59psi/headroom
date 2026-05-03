import { useState } from 'react';

interface Props {
  src: string;
  alt?: string;
  /** When true, render a square photo with the synthwave canvas backdrop. */
  hat?: boolean;
}

export function ImageLightbox({ src, alt = '', hat = false }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <img
        src={src}
        alt={alt}
        className={hat ? 'hr-hat-photo' : 'rounded'}
        style={{
          width: '100%',
          maxWidth: hat ? 480 : '100%',
          margin: '0 auto',
          aspectRatio: hat ? '1' : '4/3',
          objectFit: hat ? 'contain' : 'cover',
          cursor: 'pointer',
          display: 'block',
        }}
        onClick={() => setOpen(true)}
      />
      {open && (
        <div className="hr-lightbox-overlay" onClick={() => setOpen(false)}>
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
