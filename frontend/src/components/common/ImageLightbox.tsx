import { useState } from 'react';

interface Props {
  src: string;
  alt?: string;
}

export function ImageLightbox({ src, alt = '' }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <img
        src={src}
        alt={alt}
        className="img-fluid rounded"
        style={{ width: '50%', aspectRatio: '4/3', objectFit: 'cover', cursor: 'pointer' }}
        onClick={() => setOpen(true)}
      />
      {open && (
        <div className="hr-lightbox-overlay" onClick={() => setOpen(false)}>
          <button
            className="hr-lightbox-close"
            onClick={e => { e.stopPropagation(); setOpen(false); }}
          >
            &times;
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
