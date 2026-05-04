import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { updateHatColors } from '../../api/hats';
import type { ColorTag } from '../../types';

interface Props {
  hatId: number;
  colors: ColorTag[];
  /** dominance_rank of the row being edited (1-based). null = adding new. */
  editingRank: number | null;
  onClose: () => void;
}

const TIERS: { id: string; label: string }[] = [
  { id: 'primary', label: 'Primary' },
  { id: 'secondary', label: 'Secondary' },
  { id: 'tertiary', label: 'Tertiary' },
  { id: 'accent', label: 'Accent' },
];

export function ColorEditModal({ hatId, colors, editingRank, onClose }: Props) {
  const qc = useQueryClient();
  const isEdit = editingRank !== null;
  const target = isEdit ? colors.find(c => c.dominance_rank === editingRank) : null;

  const [hex, setHex] = useState(target?.hex_value ?? '#888888');
  const [name, setName] = useState(target?.color_name ?? '');
  const [general, setGeneral] = useState(target?.general_color ?? '');
  const [tier, setTier] = useState(target?.tier ?? 'primary');

  // Re-sync when the editing target changes (modal stays mounted between opens)
  useEffect(() => {
    if (target) {
      setHex(target.hex_value);
      setName(target.color_name);
      setGeneral(target.general_color);
      setTier(target.tier ?? 'primary');
    } else {
      setHex('#888888');
      setName('');
      setGeneral('');
      setTier('primary');
    }
  }, [target?.dominance_rank]); // eslint-disable-line react-hooks/exhaustive-deps

  const saveMut = useMutation({
    mutationFn: () => {
      const next: ColorTag = {
        color_name: name.trim() || 'unnamed',
        general_color: general.trim() || name.trim() || 'unnamed',
        hex_value: hex,
        dominance_rank: editingRank ?? colors.length + 1,
        tier,
      };
      const updated = isEdit
        ? colors.map(c => c.dominance_rank === editingRank ? next : c)
        : [...colors, next];
      return updateHatColors(hatId, updated);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['hat', hatId] });
      qc.invalidateQueries({ queryKey: ['hats'] });
      onClose();
    },
  });

  const removeMut = useMutation({
    mutationFn: () => {
      const filtered = colors
        .filter(c => c.dominance_rank !== editingRank)
        .map((c, i) => ({ ...c, dominance_rank: i + 1 }));
      return updateHatColors(hatId, filtered);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['hat', hatId] });
      qc.invalidateQueries({ queryKey: ['hats'] });
      onClose();
    },
  });

  return (
    <div className="modal" onClick={onClose}>
      <div className="modal-dialog" style={{ maxWidth: 460 }} onClick={e => e.stopPropagation()}>
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">{isEdit ? `Edit Color #${editingRank}` : 'Add Color'}</h5>
            <button type="button" className="btn-close" onClick={onClose} aria-label="Close" />
          </div>
          <div className="modal-body">
            {/* Big color preview that doubles as the picker — iOS Safari opens
                the system color wheel; desktop opens its native picker. */}
            <label
              htmlFor="hr-color-input"
              style={{
                display: 'block', width: '100%', height: 96,
                background: hex, borderRadius: 'var(--radius-sm)',
                border: '2px solid var(--border-bright)',
                boxShadow: `0 0 24px ${hex}80`,
                cursor: 'pointer', marginBottom: '0.75rem',
                position: 'relative',
              }}
              title="Tap to open the color wheel"
            >
              <span style={{
                position: 'absolute', bottom: 8, right: 12,
                fontFamily: 'var(--font-mono)', fontSize: '0.85rem',
                color: '#000', mixBlendMode: 'difference', filter: 'invert(1)',
                background: 'rgba(0,0,0,0.45)', padding: '2px 8px', borderRadius: 6,
              }}>{hex.toUpperCase()}</span>
            </label>
            <input
              id="hr-color-input"
              type="color"
              value={hex}
              onChange={e => setHex(e.target.value)}
              style={{ position: 'absolute', width: 1, height: 1, opacity: 0, pointerEvents: 'none' }}
            />

            <label className="form-label">Hex (or paste a value)</label>
            <input
              type="text"
              className="form-control mb-3"
              value={hex}
              onChange={e => {
                const v = e.target.value.trim();
                if (/^#?[0-9a-fA-F]{6}$/.test(v)) {
                  setHex(v.startsWith('#') ? v : `#${v}`);
                }
              }}
              autoComplete="off"
            />

            <label className="form-label">Specific name</label>
            <input
              type="text"
              className="form-control mb-3"
              placeholder="e.g. cobalt blue"
              value={name}
              onChange={e => setName(e.target.value)}
            />

            <label className="form-label">General color (for filters)</label>
            <input
              type="text"
              className="form-control mb-3"
              placeholder="e.g. blue"
              value={general}
              onChange={e => setGeneral(e.target.value)}
            />

            <label className="form-label">Tier</label>
            <select className="form-select" value={tier} onChange={e => setTier(e.target.value)}>
              {TIERS.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>

            {(saveMut.error || removeMut.error) && (
              <div className="alert alert-danger mt-3 mb-0 small">
                {String(saveMut.error || removeMut.error)}
              </div>
            )}
          </div>
          <div className="modal-footer">
            {isEdit && (
              <button
                type="button"
                className="btn btn-outline-danger me-2"
                onClick={() => { if (confirm('Remove this color?')) removeMut.mutate(); }}
                disabled={removeMut.isPending}
                style={{ marginRight: 'auto' }}
              >
                Remove
              </button>
            )}
            <button type="button" className="btn btn-outline-secondary" onClick={onClose}>Cancel</button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => saveMut.mutate()}
              disabled={saveMut.isPending}
            >
              {saveMut.isPending ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
