import type { ColorTag } from '../../types';

export function ColorSwatches({ colors, showLabels = true }: { colors: ColorTag[]; showLabels?: boolean }) {
  if (!colors.length) return null;
  const uniqueGenerals = [...new Set(colors.map(c => c.general_color).filter(Boolean))];
  return (
    <div>
      <div className="color-swatches">
        {colors.map((c) => (
          <div
            key={c.dominance_rank}
            className="color-swatch"
            style={{ backgroundColor: c.hex_value, color: c.hex_value }}
            title={`${c.general_color || c.color_name} (${c.hex_value})`}
          />
        ))}
      </div>
      {showLabels && uniqueGenerals.length > 0 && (
        <div className="text-secondary small" style={{ marginTop: 6, letterSpacing: '0.04em' }}>
          {uniqueGenerals.join(' · ')}
        </div>
      )}
    </div>
  );
}
