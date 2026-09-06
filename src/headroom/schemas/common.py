"""Field types shared by the wire schemas.

Two things every write body needs and none of them had:

**Money that is a number.** `purchase_price: float | None` accepted `-20`,
`1e308`, `Infinity` and `NaN`. A negative cost basis rendered `PAID $-5` and
`$-5.00/wear`; `Infinity` made every total on the valuation page `$inf`; and
`NaN` was the quiet one — SQLite stores it as NULL, so `resale_price: NaN`
produced a row with no price, `scope='manual'` and `source='Entered
manually'`, immune to every refresh forever while holding nothing.

**Text that is text.** Every string column took whatever arrived: a
500-character room name (its `String(100)` is not enforced by SQLite) that
turned a `<select>` 5,205 px wide, NUL bytes, a bidi override that made a
room called `evil` read `live` in every list, 20,000-character notes, and
`""` stored as `''` where `"   "` stored as NULL because a `.get()` truthiness
check skipped the canonicalizer for one and not the other. `CleanText` strips
the control characters that can only mislead, trims, folds empty to `None`,
and caps the length at the column's.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BeforeValidator, Field

#: Non-negative, finite, and under a million — no hat has ever cost more, and
#: `1e308` rendered as `$1e+308` in the purchases list. `allow_inf_nan=False` is what refuses the
#: `NaN` that SQLite would have stored as a NULL price stamped `manual`.
Money = Annotated[float, Field(ge=0, le=1_000_000, allow_inf_nan=False)]

#: Bidirectional and invisible formatting controls a name must not carry: the
#: explicit embeddings/overrides/isolates (U+202A–U+202E, U+2066–U+2069), the
#: marks (U+200E, U+200F, U+061C). ZWJ and variation selectors are NOT here —
#: they are how flag and family emoji are spelled.
_BIDI_CONTROLS = frozenset(
    "\u202a\u202b\u202c\u202d\u202e"   # LRE RLE PDF LRO RLO
    "\u2066\u2067\u2068\u2069"          # LRI RLI FSI PDI
    "\u200e\u200f\u061c"                 # LRM RLM ALM
)


def _cleaner(multiline: bool):
    keep_ws = "\n\t" if multiline else ""

    def clean(value: object) -> object:
        if not isinstance(value, str):
            return value
        kept = "".join(
            ch for ch in value
            if ch not in _BIDI_CONTROLS and (ch in keep_ws or (ord(ch) >= 0x20 and ch != "\x7f"))
        )
        kept = kept.strip()
        return kept or None

    return clean


def clean_text(max_length: int, *, multiline: bool = False, required: bool = False):
    """A string field: control characters stripped, trimmed, empty → None.

    `multiline` keeps newlines and tabs (notes); a name gets neither.
    Optional by default — the cleaner runs BEFORE the `str | None` union, so
    `"   "` becomes `None` rather than failing the `str` half. `required`
    makes an emptied value a validation error instead (a room needs a name).
    """
    # The length cap sits on the `str` member, not on the union: a constraint
    # on `str | None` is applied to `None` too and blows up on it.
    sized = Annotated[str, Field(max_length=max_length)]
    base = sized if required else sized | None
    return Annotated[base, BeforeValidator(_cleaner(multiline))]


# Sized to the columns in `models/hat.py`, so the schema refuses what the
# database would silently truncate — or, on SQLite, silently keep.
Brand = clean_text(80)
ModelName = clean_text(120)
Colorway = clean_text(120)
Series = clean_text(160)
Construction = clean_text(80)
LogoDetected = clean_text(255)
StyleDescriptor = clean_text(120)
Counterparty = clean_text(120)
ShortNotes = clean_text(2_000, multiline=True)
LongNotes = clean_text(10_000, multiline=True)
RoomName = clean_text(100, required=True)
OptionalRoomName = clean_text(100)
