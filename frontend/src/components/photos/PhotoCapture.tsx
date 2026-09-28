import { lazy, Suspense, useEffect, useRef, useState } from 'react';

// The cropper (react-easy-crop and its canvas work) loads when a photo is
// picked, not with the app: every page that can take a photo would otherwise
// carry it in the one bundle a phone downloads before its first paint.
const PhotoCropper = lazy(() => import('./PhotoCropper').then(m => ({ default: m.PhotoCropper })));

interface Props {
  onCapture: (file: File) => void;
  previewUrl?: string | null;
  /** Render only the "Replace photo" button — the page shows the photo itself. */
  hidePreview?: boolean;
  /** Classes for the change/replace button, so it can sit in a page's action row. */
  buttonClassName?: string;
}

/**
 * Anything a browser calls an image, plus HEIC/HEIF by name: a HEIC dragged
 * in from a Mac's Finder often arrives with an empty `type`, and the server
 * converts HEIC — rejecting it here would refuse a photo the backend takes.
 */
function isImage(file: File): boolean {
  return file.type.startsWith('image/') || /\.(heic|heif)$/i.test(file.name);
}

function hasFiles(e: React.DragEvent): boolean {
  return Array.from(e.dataTransfer?.types ?? []).includes('Files');
}

export function PhotoCapture({
  onCapture,
  previewUrl,
  hidePreview,
  buttonClassName = 'btn btn-outline-secondary w-100',
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [pending, setPending] = useState<{ file: File; url: string } | null>(null);
  const [dragging, setDragging] = useState(false);

  // Revoke the temporary blob URL when we're done with it
  useEffect(() => {
    return () => {
      if (pending) URL.revokeObjectURL(pending.url);
    };
  }, [pending]);

  /**
   * Every route in — picker, camera, drop — goes through the cropper.
   *
   * Only a DROP is filtered to images (below): anything can be dragged in.
   * The picker already asked the OS for `image/*`, and a file it hands back
   * with a blank type (an extension the OS has no MIME entry for) is still
   * the photo that was chosen — filtering it here made the tap silently do
   * nothing, where it used to reach the cropper and the upload.
   */
  function take(file: File | undefined) {
    if (!file) return;
    setPending({ file, url: URL.createObjectURL(file) });
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    take(e.target.files?.[0]);
    e.target.value = '';
  }

  /** Dismissing the cropper must NOT upload — Cancel means cancel. */
  function discard() {
    setPending(null);
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

  const open = () => inputRef.current?.click();

  // Drag-and-drop on a desktop or an iPad with a second app open: the photo
  // is usually already on screen in Finder or Photos, and a file dialog is a
  // detour to find it again. Not offered on the bare "Replace photo" button,
  // which has no area worth aiming a drop at.
  const dropHandlers = hidePreview ? {} : {
    onDragOver: (e: React.DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      setDragging(true);
    },
    onDragLeave: (e: React.DragEvent) => {
      // `dragleave` fires on every child boundary; only a leave that exits
      // the whole zone ends the highlight.
      if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
    },
    onDrop: (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      take(Array.from(e.dataTransfer.files).find(isImage));
    },
  };

  return (
    <div className={`hr-photo-capture${dragging ? ' is-dragging' : ''}`} {...dropHandlers}>
      {hidePreview ? (
        <button type="button" className={buttonClassName} onClick={open}>Replace photo</button>
      ) : previewUrl ? (
        <>
          <img src={previewUrl} alt="Preview" className="hr-hat-photo hr-photo-preview" />
          <button type="button" className={buttonClassName} onClick={open}>Change photo</button>
        </>
      ) : (
        // The empty square IS the control. It used to be a dashed "NO PHOTO"
        // placard with a separate "Capture / Upload" button under it — two
        // things to read before the one thing to tap.
        <button type="button" className="hr-photo-drop" onClick={open}>
          <svg className="hr-photo-drop-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path
              d="M4 8h3l1.6-2.4A1.5 1.5 0 0 1 9.9 5h4.2a1.5 1.5 0 0 1 1.3.6L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"
              fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"
            />
            <circle cx="12" cy="13" r="3.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
          </svg>
          <span className="hr-photo-drop-title">Add a photo</span>
          <span className="hr-photo-drop-hint">
            Take one or choose from your library
            <span className="hr-drop-hint-fine"> — or drop an image here</span>
          </span>
        </button>
      )}
      {/* No `capture` attribute on purpose. `capture="environment"` doesn't
          *prefer* the camera, it FORCES it: iOS and Android skip the picker
          entirely and open the rear camera, so an existing photo can't be
          chosen at all. Plain `accept="image/*"` gets the normal action sheet
          — Photo Library / Take Photo / Browse — which still reaches the
          camera in one extra tap while making the library reachable at all. */}
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        aria-label="Choose a photo"
        onChange={handleChange}
        hidden
      />

      {pending && (
        <Suspense fallback={<p className="text-secondary small mt-2 mb-0" role="status">Opening the cropper…</p>}>
          <PhotoCropper
            imageUrl={pending.url}
            filename={pending.file.name}
            onCancel={discard}
            onUseOriginal={useOriginal}
            onCropped={handleCropped}
          />
        </Suspense>
      )}
    </div>
  );
}
