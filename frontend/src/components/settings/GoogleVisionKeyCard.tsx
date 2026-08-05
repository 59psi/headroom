import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getGoogleVisionKeyStatus, setGoogleVisionKey, deleteGoogleVisionKey,
} from '../../api/settings';

export function GoogleVisionKeyCard() {
  const qc = useQueryClient();
  const visionKey = useQuery({
    queryKey: ['settings', 'google-vision-key'],
    queryFn: getGoogleVisionKeyStatus,
  });
  const [visionKeyDraft, setVisionKeyDraft] = useState('');

  const saveVisionKeyMut = useMutation({
    mutationFn: () => setGoogleVisionKey(visionKeyDraft.trim()),
    onSuccess: () => {
      setVisionKeyDraft('');
      qc.invalidateQueries({ queryKey: ['settings', 'google-vision-key'] });
    },
  });

  const deleteVisionKeyMut = useMutation({
    mutationFn: deleteGoogleVisionKey,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings', 'google-vision-key'] }),
  });

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Google Vision Key (fallback)</div>
        <p className="text-secondary small mb-3">
          Optional. When Claude is unavailable, hats still get color swatches from the
          photo cutout — add a Google Cloud Vision API key to also detect the brand
          from its logo. Create one at{' '}
          <a href="https://console.cloud.google.com/apis/library/vision.googleapis.com" target="_blank" rel="noopener noreferrer">
            console.cloud.google.com
          </a>{' '}
          (enable the Cloud Vision API, then create an API key).
        </p>

        {visionKey.data?.configured ? (
          <div className="mb-3">
            <div className="hr-metric mb-2">
              <div className="hr-metric-label">Active key ({visionKey.data.source})</div>
              <div className="hr-metric-value font-mono">{visionKey.data.masked}</div>
            </div>
            <button
              type="button"
              className="btn btn-outline-danger btn-sm"
              onClick={() => { if (confirm('Remove Google Vision key?')) deleteVisionKeyMut.mutate(); }}
            >
              Remove key
            </button>
          </div>
        ) : (
          <p className="text-muted small mb-3">No key configured — fallback provides colors only.</p>
        )}

        <label className="form-label">{visionKey.data?.configured ? 'Replace key' : 'New key'}</label>
        <div className="d-flex gap-2 flex-wrap">
          <input
            type="password"
            className="form-control flex-grow-1"
            style={{ minWidth: 200 }}
            placeholder="AIzaSy..."
            value={visionKeyDraft}
            onChange={e => setVisionKeyDraft(e.target.value)}
            autoComplete="off"
          />
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => saveVisionKeyMut.mutate()}
            disabled={!visionKeyDraft.trim() || saveVisionKeyMut.isPending}
          >
            {saveVisionKeyMut.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
        {saveVisionKeyMut.error && (
          <div className="alert alert-danger mt-3 mb-0 small">{String(saveVisionKeyMut.error)}</div>
        )}
      </div>
    </div>
  );
}
