import { useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getLogo, uploadLogo, deleteLogo } from '../../api/settings';

export function LogoCard() {
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const logo = useQuery({ queryKey: ['settings', 'logo'], queryFn: getLogo });

  const uploadMut = useMutation({
    mutationFn: (file: File) => uploadLogo(file),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings', 'logo'] }),
  });

  const deleteLogoMut = useMutation({
    mutationFn: deleteLogo,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings', 'logo'] }),
  });

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) uploadMut.mutate(file);
  }

  if (logo.isLoading) {
    return (
      <div className="card mb-3">
        <div className="card-body">
          <div className="card-title">Site Logo</div>
          <p className="text-secondary small mb-0">Loading…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Site Logo</div>
        <p className="text-secondary small mb-3">
          Shown in the navbar and home hero. Auto-resized to fit (96px tall).
          JPEG, PNG, WebP, or HEIC.
        </p>

        {logo.data?.logo_path ? (
          <div className="mb-3">
            <div
              className="d-block mb-2 p-3"
              style={{
                background: 'rgba(0,0,0,0.3)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-sm)',
                textAlign: 'center',
              }}
            >
              <img
                src={`/uploads/${logo.data.logo_path}`}
                alt="Current logo"
                style={{ maxHeight: 96, objectFit: 'contain' }}
              />
            </div>
            <div className="d-flex gap-2 flex-wrap">
              <button
                type="button"
                className="btn btn-outline-secondary btn-sm"
                onClick={() => inputRef.current?.click()}
                disabled={uploadMut.isPending}
              >
                {uploadMut.isPending ? 'Uploading…' : 'Replace Logo'}
              </button>
              <button
                type="button"
                className="btn btn-outline-danger btn-sm"
                onClick={() => { if (confirm('Remove logo?')) deleteLogoMut.mutate(); }}
              >
                Remove
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            className="btn btn-outline-primary"
            onClick={() => inputRef.current?.click()}
            disabled={uploadMut.isPending}
          >
            {uploadMut.isPending ? 'Uploading…' : 'Upload Logo'}
          </button>
        )}

        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          onChange={handleFileChange}
          hidden
        />

        {uploadMut.error && (
          <div className="alert alert-danger mt-3">{String(uploadMut.error)}</div>
        )}
      </div>
    </div>
  );
}
