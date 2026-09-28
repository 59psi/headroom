import { useEffect, useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getLogo, uploadLogo, deleteLogo } from '../../api/settings';
import { logoSrc } from '../../lib/photo';
import { ErrorNote } from '../common/ErrorNote';
import { useConfirm } from '../ui/Dialogs';
import { Panel } from '../ui/Panel';
import { Skeleton } from '../ui/Skeleton';
import { StatusPill } from '../ui/StatusPill';
import { useToast } from '../ui/Toast';

import type { LogoStatus } from '../../types';

const LOGO_KEY = ['settings', 'logo'] as const;

export function LogoCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const inputRef = useRef<HTMLInputElement>(null);
  const logo = useQuery({ queryKey: LOGO_KEY, queryFn: getLogo });

  // The picked file, shown the moment it is picked while the upload runs, so
  // the card answers the tap instead of sitting unchanged for the seconds the
  // server spends decoding and resizing. Replaced by the server's copy after.
  const [preview, setPreview] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  const uploadMut = useMutation({
    mutationFn: (file: File) => uploadLogo(file),
    // The response carries the new file's `version`, so writing it into the
    // shared query re-points every logo on the page (this card, the navbar,
    // the home hero) at the new image — the path itself never changes.
    onSuccess: res => {
      qc.setQueryData<LogoStatus>(LOGO_KEY, res);
      toast.success('Logo updated');
    },
    // The refetch is not awaited (not returned): the upload's own answer is
    // already in the cache, and "Uploading" should end when the upload does.
    onSettled: () => {
      setPreview(null);
      void qc.invalidateQueries({ queryKey: LOGO_KEY });
    },
  });

  // Optimistic: the navbar and the home hero read the same query, so the logo
  // leaves all three at once. The server's answer is certain (the route only
  // deletes a file), and a failure puts the old status back.
  const removeMut = useMutation({
    mutationFn: () => deleteLogo(),
    onMutate: async () => {
      await qc.cancelQueries({ queryKey: LOGO_KEY });
      const prev = qc.getQueryData<LogoStatus>(LOGO_KEY);
      qc.setQueryData<LogoStatus>(LOGO_KEY, { logo_path: null });
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(LOGO_KEY, ctx.prev);
    },
    onSuccess: () => toast.success('Logo removed'),
    onSettled: () => { void qc.invalidateQueries({ queryKey: LOGO_KEY }); },
  });

  function start(file: File) {
    // jsdom (and very old WebKit) has no object URLs; the upload still runs,
    // it just shows the old logo until the new one lands.
    setPreview(typeof URL.createObjectURL === 'function' ? URL.createObjectURL(file) : null);
    // The ErrorNote below shows the FIRST failure in its list, so an earlier
    // refused removal would otherwise stand in for this upload's own answer.
    if (removeMut.isError) removeMut.reset();
    uploadMut.mutate(file);
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    // Cleared so picking the same file again (after a failed upload) still
    // fires `change`.
    e.target.value = '';
    if (file) start(file);
  }

  async function remove() {
    const ok = await confirm({
      title: 'Remove logo?',
      body: 'The navbar and the home page show no logo until you upload another.',
      confirmLabel: 'Remove logo',
      tone: 'danger',
    });
    if (!ok) return;
    // Same reason as in `start`: a stale "Invalid image type" from an
    // earlier upload must not be the reason shown when THIS removal is
    // refused and the logo comes back.
    if (uploadMut.isError) uploadMut.reset();
    removeMut.mutate();
  }

  const path = logo.data?.logo_path ?? null;
  const shown = preview ?? logoSrc(logo.data);
  const uploading = uploadMut.isPending;

  const status = uploading
    ? <StatusPill tone="busy">Uploading</StatusPill>
    : logo.data
      ? (path ? <StatusPill tone="ok">Set</StatusPill> : <StatusPill tone="off">Not set</StatusPill>)
      : null;

  return (
    <Panel
      title="Site logo"
      status={status}
      description="Shown in the navbar and home hero, scaled down to fit 96px tall. JPEG, PNG, WebP or HEIC."
      // No buttons until the status is known, as before this card was a
      // Panel: "Upload logo" as the primary button is itself a claim that
      // there is no logo, and it flipped to "Replace logo" a moment later on
      // every visit to a card that had one. A FAILED fetch still offers the
      // upload — that is the way to put a logo back if it is missing.
      footer={logo.isLoading ? undefined : (
        <>
          <button
            type="button"
            className={path ? 'btn btn-outline-secondary' : 'btn btn-primary'}
            onClick={() => inputRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? 'Uploading…' : path ? 'Replace logo' : 'Upload logo'}
          </button>
          {path && (
            <button
              type="button"
              className="btn btn-outline-danger"
              onClick={remove}
              disabled={uploading || removeMut.isPending}
            >
              Remove
            </button>
          )}
        </>
      )}
    >
      {/* Also a drop target, for the desktop: dragging a file from the
          Finder onto the old logo is the gesture people try first. The
          buttons below remain the way in on touch and from the keyboard. */}
      <div
        className={`hr-sitelogo-stage${shown ? ' has-logo' : ''}${dragging ? ' is-dragging' : ''}${uploading ? ' is-busy' : ''}`}
        onDragOver={e => { e.preventDefault(); if (!dragging) setDragging(true); }}
        onDragLeave={e => {
          // Moving onto the <img> inside counts as leaving the stage; only
          // leaving it for somewhere outside should drop the highlight.
          if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
          setDragging(false);
        }}
        onDrop={e => {
          e.preventDefault();
          setDragging(false);
          const file = e.dataTransfer.files?.[0];
          // Not while loading either: the buttons are not up yet, and an
          // upload racing the first fetch has no status to replace.
          if (file && !uploading && !logo.isLoading) start(file);
        }}
      >
        {logo.isLoading ? (
          <Skeleton height={96} width="55%" />
        ) : shown ? (
          <img
            src={shown}
            alt={preview ? 'New logo (uploading)' : 'Current logo'}
            className="hr-sitelogo-img"
            // A HEIC picked in a browser that cannot draw one: fall back to
            // the current logo rather than a broken-image glyph. The upload
            // is unaffected — the server converts it.
            onError={() => { if (preview) setPreview(null); }}
          />
        ) : logo.data ? (
          // Only on an ANSWER of "no logo". A failed fetch is not that: the
          // ErrorNote says what went wrong and the stage stays blank rather
          // than stating something nobody checked.
          <p className="hr-sitelogo-empty">
            No logo yet — the navbar shows the name alone.
            <span className="hr-sitelogo-drophint"> Drop an image here to add one.</span>
          </p>
        ) : null}
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        onChange={handleFileChange}
        hidden
      />

      <ErrorNote of={[logo, uploadMut, removeMut]} className="mt-3" />
    </Panel>
  );
}
