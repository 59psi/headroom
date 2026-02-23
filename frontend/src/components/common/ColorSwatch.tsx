import type { ColorTag } from '../../types';

export function ColorSwatches({ colors }: { colors: ColorTag[] }) {
  if (!colors.length) return null;
  return (
    <div className="color-swatches">
      {colors.map((c) => (
        <div
          key={c.dominance_rank}
          className="color-swatch"
          style={{ backgroundColor: c.hex_value }}
          title={c.color_name}
        />
      ))}
    </div>
  );
}
