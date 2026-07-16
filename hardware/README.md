# Hardware

3D-printable models that pair with Headroom.

## Melin case rack — [`melin-stand-slim.zip`](melin-stand-slim.zip)

A modular, stackable, slide-in shelf system for the **Melin 3-Hat Travel Case**
(250 × 200 × 150 mm). The sloped lid means the cases can't be stacked directly —
each rack module gives a case its own slide-in bay with only ~11.5 mm of
vertical overhead, and modules stack via tapered pegs at the four corner
columns. Print one bay per case and grow the tower over time; an optional top
cap ties the uppermost pegs together and gives a flat top.

**[⬇ Download melin-stand-slim.zip](melin-stand-slim.zip)** (240 KB)

### What's inside

| File | What it is |
|---|---|
| `melin-hat-case-rack.scad` | Parametric OpenSCAD source — part selection, case dimensions, and clearances all exposed in the customizer |
| `melin-rack-rack.stl` | One stackable bay — print one per case |
| `melin-rack-top_cap.stl` | Optional lid frame for the top of the stack |
| `melin-rack-fit_test.stl` | Small peg + socket coupon (~10 min) — print this **first** to dial in `fit_clear` for your filament |

### Print notes

Dialed in on a Bambu Lab H2D; any printer whose bed fits the ~222 × 258 mm
footprint (~168 mm tall with pegs) works.

- Print in the modeled orientation (floor on bed). **Zero supports needed** —
  every feature is vertical, chamfered, ramped, or a short bridge.
- Suggested: PETG-HF or PLA Basic, 0.4 mm nozzle, 0.2 mm layers, 3 walls,
  10–15% infill, no brim.
- To slide cases in wide-side-first instead (shallower, wider rack), swap
  `case_l` and `case_w` in the source.
