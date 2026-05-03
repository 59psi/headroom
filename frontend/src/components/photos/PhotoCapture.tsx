import { useEffect, useRef, useState } from 'react';
import { PhotoCropper } from './PhotoCropper';

interface Props {
  onCapture: (file: File) => void;
  previewUrl?: string | null;
  hidePreview?: boolean;
}

export function PhotoCapture({ onCapture, previewUrl, hidePreview }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [pending, setPending] = useState<{ file: File; url: string } | null>(null);

  // Revoke the temporary blob URL when we're done with it
  useEffect(() => {
    return () => {
      if (pending) URL.revokeObjectURL(pending.url);
    };
  }, [pending]);

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setPending({ file, url: URL.createObjectURL(file) });
    e.target.value = '';
  }

  function useOriginal() {
    if (!pending) return;
    onCapture(pending.file);
    setPending(null);
  }

  function handleCropped(cropped: File) {
    onCapture(cropped);
    setPending(null);
  }

  return (
    <div>
      {!hidePreview && (
        previewUrl ? (
          <img
            src={previewUrl}
            alt="Preview"
            className="hr-hat-photo mb-2"
            style={{ aspectRatio: '1', objectFit: 'contain', width: '100%', display: 'block' }}
          />
        ) : (
          <div
            className="d-flex align-items-center justify-content-center mb-2 text-muted"
            style={{
              width: '100%',
              aspectRatio: '1',
              background: 'rgba(0, 0, 0, 0.3)',
              border: '1px dashed var(--border)',
              borderRadius: 'var(--radius-sm)',
              fontFamily: 'var(--font-heading)',
              fontSize: '0.75rem',
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
            }}
          >
            No Photo
          </div>
        )
      )}
      <button
        type="button"
        className="btn btn-outline-primary w-100"
        onClick={() => inputRef.current?.click()}
      >
        {hidePreview ? 'Replace Photo' : previewUrl ? 'Change Photo' : 'Capture / Upload'}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        capture="environment"
        onChange={handleChange}
        hidden
      />

      {pending && (
        <PhotoCropper
          imageUrl={pending.url}
          filename={pending.file.name}
          onCancel={useOriginal /* skipping crop = use original */}
          onCropped={handleCropped}
        />
      )}
    </div>
  );
}
