import { useState } from 'react';
import { Modal } from './Modal';
import { ErrorNote } from './ErrorNote';
import { Segmented } from '../ui/Segmented';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { updateHatColors } from '../../api/hats';
import { COLOR_TIERS, tierForRank, type Tier } from '../../lib/colorTiers';
import { invalidateHatViews } from '../../lib/invalidate';
import { qk } from '../../lib/queryKeys';
import { useToast } from '../ui/Toast';
import { useConfirm } from '../ui/Dialogs';
import type { ColorTag, ColorTagWrite, HatRead } from '../../types';

interface Props {
  hatId: number;
  colors: ColorTag[];
  /** dominance_rank of the row being edited (1-based). null = adding new. */
  editingRank: number | null;
  onClose: () => void;
}

export function ColorEditModal({ hatId, colors, editingRank, onClose }: Props) {
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const isEdit = editingRank !== null;
  const target = isEdit ? colors.find(c => c.dominance_rank === editingRank) : null;

  const [hex, setHex] = useState(target?.hex_value ?? '#888888');
  // What's in the text box, kept apart from the committed `hex`. The input
  // used to write straight to `hex` and only when the value already matched
  // a full 6-digit pattern — so every partial keystroke was rejected and the
  // box snapped back. You could paste a whole value, never type one.
  const [hexText, setHexText] = useState(target?.hex_value ?? '#888888');
  const [name, setName] = useState(target?.color_name ?? '');
  const [general, setGeneral] = useState(target?.general_color ?? '');
  // A new color starts at the tier its position implies, as the Edit form's
  // do — not "primary" for a fourth color nobody called primary.
  const [tier, setTier] = useState<Tier>(target?.tier ?? tierForRank(colors.length + 1));

  // No re-sync effect: `HatDetailPage` mounts this modal only while it is open
  // (`colorEditOpen !== null && <ColorEditModal …/>`), so every open is a fresh
  // instance and the `useState` seeds above ARE the sync. An effect keyed on
  // `target?.dominance_rank` sat here for a mount-once modal that no longer
  // exists, and could never fire.

  /**
   * The PUT answers with the hat as stored — including the `general_color`
   * the server derives when the box is left blank — so write that straight
   * into the page's cache. The palette under the modal is correct the moment
   * it closes instead of a refetch later, and it is the server's answer, not
   * a guess at it. The invalidations stay, and they are the whole set: the
   * palette shows on the collection lists, the room page's loose hats, case
   * pages and search results — this used to refresh only `['hat', id]` and
   * `['hats']`, so a recolored loose hat kept its old swatches on its room.
   */
  function applySaved(hat: HatRead | undefined) {
    if (hat && hat.id === hatId) qc.setQueryData(qk.hat(hatId), hat);
    void invalidateHatViews(qc, hatId);
  }

  const saveMut = useMutation({
    mutationFn: () => {
      const next: ColorTagWrite = {
        // Blank means "name it from the hex" — the server derives the palette
        // name, the same way it derives a blank general color. It used to be
        // stored as the literal word "unnamed".
        color_name: name.trim() || null,
        // Blank means "derive it from the hex" — the server does that, snapping
        // to the filter palette. Don't substitute the *specific* name here: it's
        // free text ("cobalt blue"), and since a typed general_color is now
        // honored verbatim, sending it would store an off-palette value and
        // quietly drop the hat out of the color-chip search.
        general_color: general.trim(),
        hex_value: hex,
        tier,
      };
      // Position IS the rank on write — the server ignores a sent
      // `dominance_rank` — so an edit replaces its row in place and an add
      // appends.
      const updated: ColorTagWrite[] = isEdit
        ? colors.map(c => c.dominance_rank === editingRank ? next : c)
        : [...colors, next];
      return updateHatColors(hatId, updated);
    },
    onSuccess: hat => {
      applySaved(hat);
      toast.success(isEdit ? 'Color saved' : 'Color added');
      onClose();
    },
  });

  const removeMut = useMutation({
    // The rest keep their order, and so their ranks close up: position is
    // the rank the server stores.
    mutationFn: () => updateHatColors(hatId, colors.filter(c => c.dominance_rank !== editingRank)),
    onSuccess: hat => {
      applySaved(hat);
      toast.success('Color removed');
      onClose();
    },
  });

  async function remove() {
    const ok = await confirm({
      title: 'Remove this color?',
      body: 'The colors after it move up one place in the palette.',
      confirmLabel: 'Remove color',
      tone: 'danger',
    });
    if (ok) removeMut.mutate();
  }

  return (
    <Modal title={isEdit ? `Edit color #${editingRank}` : 'Add color'} onClose={onClose} maxWidth={460}
      footer={(
        <>
          {isEdit && (
            <button
              type="button"
              className="btn btn-outline-danger hr-modal-foot-start"
              onClick={() => { void remove(); }}
              disabled={removeMut.isPending}
            >
              {removeMut.isPending ? 'Removing…' : 'Remove'}
            </button>
          )}
          <button type="button" className="btn btn-outline-secondary" onClick={onClose}>Cancel</button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => saveMut.mutate()}
            disabled={saveMut.isPending}
          >
            {saveMut.isPending ? 'Saving…' : isEdit ? 'Save' : 'Add color'}
          </button>
        </>
      )}
    >

      {/* Big color preview that doubles as the picker — iOS Safari opens
          the system color wheel; desktop opens its native picker. The fill
          and its glow are the only inline styles left: they ARE the value. */}
      <label
        htmlFor="hr-color-input"
        className="hr-color-preview"
        style={{ background: hex, boxShadow: `0 0 24px ${hex}80` }}
        title="Tap to open the color wheel"
      >
        <span className="hr-color-preview-hex">{hex.toUpperCase()}</span>
      </label>
      <input
        id="hr-color-input"
        type="color"
        aria-label="Pick a color"
        className="hr-offscreen-input"
        value={hex}
        onChange={e => { setHex(e.target.value); setHexText(e.target.value); }}
      />

      <label className="form-label" htmlFor="color-hex">Hex</label>
      <input
        id="color-hex"
        type="text"
        className="form-control mb-3 font-mono"
        value={hexText}
        onChange={e => {
          setHexText(e.target.value);
          const v = e.target.value.trim();
          if (/^#?[0-9a-fA-F]{6}$/.test(v)) {
            setHex(v.startsWith('#') ? v : `#${v}`);
          }
        }}
        autoComplete="off"
        spellCheck={false}
      />

      <div className="hr-color-names">
        <div>
          <label className="form-label" htmlFor="color-specific-name">Specific name</label>
          <input
            id="color-specific-name"
            type="text"
            className="form-control"
            placeholder="e.g. cobalt blue"
            value={name}
            onChange={e => setName(e.target.value)}
          />
        </div>
        <div>
          <label className="form-label" htmlFor="color-general-name">General color (for filters)</label>
          <input
            id="color-general-name"
            type="text"
            className="form-control"
            placeholder="e.g. blue"
            value={general}
            onChange={e => setGeneral(e.target.value)}
          />
        </div>
      </div>

      {/* Chips rather than a <select>: four words, one tap. */}
      <span className="form-label" id="color-tier-label">Tier</span>
      <Segmented
        variant="chips"
        labelledBy="color-tier-label"
        options={COLOR_TIERS}
        value={tier}
        onChange={setTier}
      />

      <ErrorNote of={[saveMut, removeMut]} className="mt-3 mb-0" />
    </Modal>
  );
}
