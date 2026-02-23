import { useRef } from 'react';

interface Props {
  onCapture: (file: File) => void;
  previewUrl?: string | null;
}

export function PhotoCapture({ onCapture, previewUrl }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) onCapture(file);
  }

  return (
    <div className="mb-3">
      {previewUrl ? (
        <img src={previewUrl} alt="Preview" className="img-fluid rounded mb-2" style={{ aspectRatio: '4/3', objectFit: 'cover', width: '100%' }} />
      ) : (
        <div className="d-flex align-items-center justify-content-center rounded mb-2 text-secondary" style={{ width: '100%', aspectRatio: '4/3', background: 'var(--color-border)' }}>
          No photo
        </div>
      )}
      <button
        type="button"
        className="btn btn-outline-secondary w-100"
        onClick={() => inputRef.current?.click()}
      >
        {previewUrl ? 'Change Photo' : 'Take Photo'}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        capture="environment"
        onChange={handleChange}
        hidden
      />
    </div>
  );
}
