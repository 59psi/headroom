import { useCallback, useState } from 'react';
import Cropper, { type Area } from 'react-easy-crop';

interface Props {
  imageUrl: string;
  filename: string;
  onCancel: () => void;
  onCropped: (file: File) => void;
}

/**
 * Crop the source image client-side via canvas, then return a JPEG blob.
 * Free aspect ratio + 90° rotation. Skips filter / exposure adjustments —
 * those belong in a dedicated photo app, not here.
 */
async function getCroppedJpeg(
  imageSrc: string,
  area: Area,
  rotation: number,
  filename: string,
): Promise<File> {
  const img = await loadImage(imageSrc);
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('canvas 2d context unavailable');

  // Compute rotated bounding box and draw the rotated image onto a workspace
  const rad = (rotation * Math.PI) / 180;
  const sin = Math.abs(Math.sin(rad));
  const cos = Math.abs(Math.cos(rad));
  const rotatedW = Math.floor(img.width * cos + img.height * sin);
  const rotatedH = Math.floor(img.width * sin + img.height * cos);

  const work = document.createElement('canvas');
  work.width = rotatedW;
  work.height = rotatedH;
  const wctx = work.getContext('2d')!;
  wctx.translate(rotatedW / 2, rotatedH / 2);
  wctx.rotate(rad);
  wctx.drawImage(img, -img.width / 2, -img.height / 2);

  // Crop the workspace down to the requested area
  canvas.width = Math.floor(area.width);
  canvas.height = Math.floor(area.height);
  ctx.drawImage(
    work,
    Math.floor(area.x), Math.floor(area.y),
    Math.floor(area.width), Math.floor(area.height),
    0, 0,
    Math.floor(area.width), Math.floor(area.height),
  );

  const blob: Blob = await new Promise((resolve, reject) => {
    canvas.toBlob(b => {
      if (b) resolve(b);
      else reject(new Error('canvas.toBlob failed'));
    }, 'image/jpeg', 0.92);
  });

  // Always end up with a .jpg name so the backend's pipeline picks the right MIME
  const base = filename.replace(/\.[^/.]+$/, '') || 'photo';
  return new File([blob], `${base}.jpg`, { type: 'image/jpeg' });
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = (e) => reject(e);
    img.src = src;
  });
}

export function PhotoCropper({ imageUrl, filename, onCancel, onCropped }: Props) {
  const [crop, setCrop] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [croppedArea, setCroppedArea] = useState<Area | null>(null);
  const [working, setWorking] = useState(false);

  const onCropComplete = useCallback((_pct: Area, pixels: Area) => {
    setCroppedArea(pixels);
  }, []);

  async function applyCrop() {
    if (!croppedArea) return;
    setWorking(true);
    try {
      const file = await getCroppedJpeg(imageUrl, croppedArea, rotation, filename);
      onCropped(file);
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="modal" onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="modal-dialog" style={{ maxWidth: 600 }} onClick={e => e.stopPropagation()}>
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">Crop Photo</h5>
            <button type="button" className="btn-close" onClick={onCancel} aria-label="Close" />
          </div>
          <div className="modal-body" style={{ padding: 0 }}>
            <div style={{ position: 'relative', width: '100%', height: 360, background: '#000' }}>
              <Cropper
                image={imageUrl}
                crop={crop}
                zoom={zoom}
                rotation={rotation}
                aspect={undefined /* free aspect */}
                showGrid
                onCropChange={setCrop}
                onZoomChange={setZoom}
                onRotationChange={setRotation}
                onCropComplete={onCropComplete}
              />
            </div>
            <div style={{ padding: '1rem 1.25rem' }}>
              <label className="form-label">Zoom</label>
              <input
                type="range"
                min={1}
                max={3}
                step={0.05}
                value={zoom}
                onChange={e => setZoom(Number(e.target.value))}
                style={{ width: '100%' }}
              />
              <div className="d-flex gap-2 mt-2 flex-wrap">
                <button
                  type="button"
                  className="btn btn-outline-secondary btn-sm"
                  onClick={() => setRotation(r => (r + 270) % 360)}
                >↶ 90°</button>
                <button
                  type="button"
                  className="btn btn-outline-secondary btn-sm"
                  onClick={() => setRotation(r => (r + 90) % 360)}
                >↷ 90°</button>
                <button
                  type="button"
                  className="btn btn-outline-secondary btn-sm"
                  onClick={() => { setCrop({ x: 0, y: 0 }); setZoom(1); setRotation(0); }}
                >Reset</button>
              </div>
            </div>
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-outline-secondary" onClick={onCancel}>Cancel</button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={applyCrop}
              disabled={!croppedArea || working}
            >
              {working ? 'Cropping…' : 'Use This'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
