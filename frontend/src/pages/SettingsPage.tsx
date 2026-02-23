import { useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getLogo, uploadLogo, deleteLogo } from '../api/settings';
import { LoadingSpinner } from '../components/common/LoadingSpinner';

export function SettingsPage() {
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  const logo = useQuery({ queryKey: ['settings', 'logo'], queryFn: getLogo });

  const uploadMut = useMutation({
    mutationFn: async (file: File) => {
      setUploading(true);
      try {
        return await uploadLogo(file);
      } finally {
        setUploading(false);
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings', 'logo'] });
    },
  });

  const deleteMut = useMutation({
    mutationFn: deleteLogo,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings', 'logo'] });
    },
  });

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) uploadMut.mutate(file);
  }

  if (logo.isLoading) return <LoadingSpinner />;

  return (
    <>
      <h1 className="mb-3">Settings</h1>

      <div className="card mb-3">
        <div className="card-body">
          <h6 className="card-title text-secondary mb-3">Site Logo</h6>
          <p className="text-secondary small mb-3">
            Upload a logo to display in the navbar and homepage hero. The image will be
            automatically resized proportionally to fit (max 96px tall).
          </p>

          {logo.data?.logo_path ? (
            <div className="mb-3">
              <img
                src={`/uploads/${logo.data.logo_path}`}
                alt="Current logo"
                className="d-block mb-2"
                style={{ maxHeight: 96, objectFit: 'contain' }}
              />
              <div className="d-flex gap-2">
                <button
                  type="button"
                  className="btn btn-outline-secondary btn-sm"
                  onClick={() => inputRef.current?.click()}
                  disabled={uploading}
                >
                  {uploading ? 'Uploading...' : 'Replace Logo'}
                </button>
                <button
                  type="button"
                  className="btn btn-outline-danger btn-sm"
                  onClick={() => { if (confirm('Remove logo?')) deleteMut.mutate(); }}
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
              disabled={uploading}
            >
              {uploading ? 'Uploading...' : 'Upload Logo'}
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
    </>
  );
}
