"""How a product name is read: ONE tokenizer and ONE splitter.

Two modules compared names and each had its own reading. `melin_recap`
stripped punctuation (a fix CLAUDE.md records — `Odysea Hydro "Have More
Fun"` demanded the tokens `"have` and `fun"`, which no listing title has ever
carried) while `catalog_service._model_tokens` still split on whitespace, so
the SAME quoted name was priceable on the marketplace and unmatchable against
its own receipt, invisible to `is_real_product` and absent from the picker.
Neither handled a fullwidth letter: `Ｏdysea` tokenized as `dysea`, one
character from a phone keyboard away from matching nothing.

The splitters disagreed the same way: the harvest split listing titles on
`" - "` only, the analyzer's repair split on em and en dashes too, so a title
melin wrote with an em dash landed in the catalog as a model called
`Trenches Hydro — Camo` with no colorway.

Both live here now, and both sides of every comparison go through the same
functions — the CLAUDE.md rule that a normalization applied to one side is a
comparison between two alphabets.
"""

from __future__ import annotations

import functools
import unicodedata

#: Spaced separators, tried in this order. A bare `-` is never one: `A-Game`
#: is a product line and the most common one in the collection.
SEPARATORS = (" — ", " – ", " - ")


def normalize(text: str | None) -> str:
    """NFKC (fullwidth → ASCII, ligatures apart) and casefolded."""
    return unicodedata.normalize("NFKC", text or "").casefold()


def tokens(text: str | None) -> tuple[str, ...]:
    """Word tokens: letters and digits, everything else a separator.

    `A-Game` → (`a`, `game`); `"Have More Fun"` → (`have`, `more`, `fun`);
    `Ｏdysea` → (`odysea`,).
    """
    out: list[str] = []
    current: list[str] = []
    for ch in normalize(text):
        if ch.isalnum():
            current.append(ch)
        elif current:
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return tuple(out)


@functools.lru_cache(maxsize=4096)
def token_set(text: str | None) -> frozenset[str]:
    """`tokens` as a set — what containment and equality compare. Cached:
    purchase matching is quadratic and tokenizes several strings per pair."""
    return frozenset(tokens(text))


def split_model_colorway(text: str | None) -> tuple[str | None, str | None]:
    """`"Trenches Hydro — Hawaii 808"` → `("Trenches Hydro", "Hawaii 808")`.

    Splits on the FIRST spaced separator, or on a trailing parenthesized
    phrase — `Odysea Rope Hydro (WATERCOLOR)`, the other shape the analyzer
    produced before its schema forbade separators in a model name. A name
    with neither is a model with an unknown colorway. Either half can come
    back `None` when it is empty: `" - Black"` names no model at all, and
    the old title parser returned `""` for it, which then went into the
    catalog as a model.
    """
    if not text or not text.strip():
        return None, None
    for sep in SEPARATORS:
        if sep in text:
            model, _, colorway = text.partition(sep)
            return model.strip() or None, colorway.strip() or None
    stripped = text.rstrip()
    if "(" in stripped and stripped.endswith(")"):
        model, _, rest = stripped.partition("(")
        return model.strip() or None, rest.rstrip(")").strip() or None
    return text.strip() or None, None
