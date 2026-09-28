import type { ReactNode } from 'react';

/**
 * A few mutually exclusive choices shown side by side, one tap each.
 *
 * Short fixed lists — a color scope, a case type, list or gallery, which
 * phone a recipe is for, how a hat left the collection — used to be either a
 * `<select>` (two taps and, on iOS, a picker wheel for four words that fit on
 * screen at once) or a `btn-group` whose selected button was a solid gradient
 * `btn-primary`, the loudest thing on the page for what is only a filter. Then
 * four areas each hand-rolled the replacement, with four ideas of the track
 * padding, the tap height and what "selected" looks like. This is the one.
 *
 * Toggle buttons (`aria-pressed`) in a labeled group, NOT radios and NOT a
 * tablist. Each option stays a plain `button` by its own name, so a test or a
 * screen reader finds "Accents only" or "List view" as a button and hears
 * whether it is pressed; Tab walks the options like any other buttons. A
 * `tablist` promises arrow-key navigation and a `tabpanel` it controls — the
 * Settings page's section strip is one, and keeps its own markup; these
 * mostly filter or re-lay-out content that is not a panel.
 *
 * The pressed look is keyed off `aria-pressed` itself rather than a parallel
 * `is-active` class, so the style cannot disagree with what assistive tech is
 * told.
 *
 * Variants:
 *   - `segmented` — one joined strip on an inset track (filters, toggles).
 *     `fill` spreads it across its container in equal segments, the shape of
 *     a phone-width filter bar.
 *   - `chips` — separate pills that wrap (form choices in a modal, where five
 *     options need two lines on a phone; a filter row that shares a wrapping
 *     toolbar).
 */
export interface SegmentedOption<T extends string = string> {
  value: T;
  /** The visible text — or, with `iconOnly`, the accessible name and tooltip. */
  label: string;
  /** A number after the label: how many things the option would show.
   *  Omitted → no badge (so pass `undefined`, not 0, to hide an empty one). */
  count?: number;
  /** A small glyph before the label. Decorative: the label names the option. */
  icon?: ReactNode;
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
  labelledBy,
  variant = 'segmented',
  fill = false,
  iconOnly = false,
  className = '',
}: {
  options: ReadonlyArray<SegmentedOption<T>>;
  value: T;
  onChange: (next: T) => void;
  /** Accessible name when there is no visible label to point at. */
  label?: string;
  /** `id` of a visible label, preferred over `label`. */
  labelledBy?: string;
  variant?: 'segmented' | 'chips';
  /** `segmented` only: equal segments across the container. */
  fill?: boolean;
  /** Show only each option's `icon`; its `label` becomes the button's
   *  accessible name and hover tooltip. For glyphs everyone reads the same
   *  way (list, grid) — a word that needs a tooltip to decode should stay a
   *  word. */
  iconOnly?: boolean;
  /** Placement from the caller's layout (a toolbar's right edge, a width cap). */
  className?: string;
}) {
  const filled = fill && variant === 'segmented';
  return (
    <div
      className={`hr-seg is-${variant}${filled ? ' is-fill' : ''}${iconOnly ? ' is-icons' : ''}${className ? ` ${className}` : ''}`}
      role="group"
      aria-label={labelledBy ? undefined : label}
      aria-labelledby={labelledBy}
    >
      {options.map(o => (
        <button
          key={o.value}
          type="button"
          className="hr-seg-btn"
          aria-pressed={o.value === value}
          // Icon-only: the glyph is aria-hidden, so without this the button
          // would have no name at all.
          aria-label={iconOnly ? o.label : undefined}
          title={iconOnly ? o.label : undefined}
          onClick={() => onChange(o.value)}
        >
          {o.icon && <span className="hr-seg-icon" aria-hidden="true">{o.icon}</span>}
          {!iconOnly && o.label}
          {o.count !== undefined && <span className="hr-seg-count">{o.count}</span>}
        </button>
      ))}
    </div>
  );
}
