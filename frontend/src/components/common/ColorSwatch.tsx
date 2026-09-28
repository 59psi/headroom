import type { ColorTag } from '../../types';

/**
 * A hat's palette as dots, optionally with its color names under them.
 *
 * The only inline style left is each dot's color, which IS the data; the
 * names' spacing lives in the stylesheet (`.hr-swatch-names`).
 */
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
        <div className="text-secondary small hr-swatch-names">
          {uniqueGenerals.join(' · ')}
        </div>
      )}
    </div>
  );
}
