"""How a product name is read: ONE tokenizer and ONE splitter.

Two modules compared names and each had its own reading. `melin_recap`
stripped punctuation (an earlier fix — `Odysea Hydro "Have More
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
functions — because a normalization applied to only one side turns a
comparison into one between two alphabets.

So does the ONE answer to "are these the same name?" (`name_key`). There
were three: these tokens (accent-SENSITIVE, punctuation-blind), `vocabulary`'s
fold (accent-blind, punctuation-sensitive) and duplicate detection, which
borrowed the vocabulary's. `Piña`/`Pina` was one colorway to the vocabulary
and two products to the matcher; `A-Game`/`A Game` was one model to the
matcher and two hats to the duplicate report. Every comparison folds case,
width, accents AND punctuation the same way now.
"""

from __future__ import annotations

import functools
import unicodedata

#: Spaced separators, tried in this order. A bare `-` is never one: `A-Game`
#: is a product line and the most common one in the collection.
SEPARATORS = (" — ", " – ", " - ")


def fold(text: str | None) -> str:
    """The one character-level fold: width, accents and case.

    NFKD takes a fullwidth `Ｏ` to `O` and splits `ñ` into `n` plus a combining
    mark; dropping the marks leaves the base letters. Accents fold because in
    this collection they are the same drop typed with and without a long-press
    on a phone keyboard (see `vocabulary`), not two different products.
    """
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def tokens(text: str | None) -> tuple[str, ...]:
    """Word tokens: letters and digits, everything else a separator.

    `A-Game` → (`a`, `game`); `"Have More Fun"` → (`have`, `more`, `fun`);
    `Ｏdysea` → (`odysea`,); `Piña` → (`pina`,).
    """
    out: list[str] = []
    current: list[str] = []
    for ch in fold(text):
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


def name_key(text: str | None) -> str:
    """The key two spellings of one name share: its tokens, in order.

    `A-Game`, `A Game` and `a-game` → `a game`; `Piña` and `PINA` → `pina`.
    Ordered, unlike `token_set`, because a spelling is a sequence — `Grey
    Heather` is not a way of writing `Heather Grey`. Empty for a value with no
    letters or digits, which callers read as "nothing to match on".
    """
    return " ".join(tokens(text))


#: Order-line phrases that name something other than headwear. Read from the
#: TITLE, the only thing every line has: a "3 Hat Travel Case - Black" carries
#: a colorway and a price like any hat, and on the owner's history these were
#: 78 of the 95 lines the matcher could not place — an "unmatched" list that
#: was mostly cases buried the hat purchases actually waiting for a hat.
ACCESSORY_PHRASES: tuple[str, ...] = (
    "travel case", "gift card", "shipping protection", "sticker",
    "lanyard", "keychain", "tote",
)


def is_accessory(title: str | None) -> bool:
    """Whether an order line is a case, gift card or other non-hat item."""
    folded = " ".join(tokens(title))
    return any(phrase in folded for phrase in ACCESSORY_PHRASES)


def split_model_colorway(
    text: str | None, *, separated_only: bool = False
) -> tuple[str | None, str | None]:
    """`"Trenches Hydro — Hawaii 808"` → `("Trenches Hydro", "Hawaii 808")`.

    Splits on the FIRST spaced separator, or on a trailing parenthesized
    phrase — `Odysea Rope Hydro (WATERCOLOR)`, the other shape the analyzer
    produced before its schema forbade separators in a model name. A name
    with neither is a model with an unknown colorway. Either half can come
    back `None` when it is empty: `" - Black"` names no model at all, and
    the old title parser returned `""` for it, which then went into the
    catalog as a model.

    `separated_only`: a separator is the only thing that marks a colorway —
    for a seller's order line, where a trailing `(…)` is a sales tag
    (`…MAUI STRONG (RARE)` gave a hat the colorway "RARE"), not the analyzer's
    old model-name shape.
    """
    if not text or not text.strip():
        return None, None
    for sep in SEPARATORS:
        if sep in text:
            model, _, colorway = text.partition(sep)
            return model.strip() or None, colorway.strip() or None
    stripped = text.rstrip()
    if not separated_only and "(" in stripped and stripped.endswith(")"):
        model, _, rest = stripped.partition("(")
        return model.strip() or None, rest.rstrip(")").strip() or None
    return text.strip() or None, None


#: What a reseller adds to a listing about the SALE, not the hat — read as a
#: colorway, "Black (RARE)" and "Navy NEW WITH TAGS" were two colorways no
#: hat has, and once receipts fed the colorway picker they became "real".
#: Longest first, so "very rare" is taken whole before "rare".
SALES_PHRASES: tuple[tuple[str, ...], ...] = tuple(sorted(
    (tuple(p.split()) for p in (
        "new with tags", "new without tags", "new with tag", "new in box", "new in bag",
        "brand new", "nwt", "nwot", "bnwt", "nib", "new",
        "very rare", "super rare", "ultra rare", "rare", "htf", "vhtf", "hard to find",
        "limited edition", "sold out", "free shipping", "fast shipping", "ships fast",
        "authentic", "100 authentic",
    )),
    key=len, reverse=True,
))
#: The ones that cannot also BEGIN a real colorway name — "Rare Earth" or
#: "New Navy" could be one, so "rare" and "new" come off the end only.
_LEADING_SALES_PHRASES: tuple[tuple[str, ...], ...] = tuple(
    p for p in SALES_PHRASES
    if p[0] in ("nwt", "nwot", "bnwt", "nib", "brand") or p[:2] in (("new", "with"), ("new", "without"), ("new", "in"))
)
_BRACKETS = ("(", ")", "[", "]")


def _sales_phrase_at(keys: list[str], *, end: bool, phrases=SALES_PHRASES) -> int:
    """How many words of `keys` (at the end, or the start) are one sales phrase."""
    for phrase in phrases:
        n = len(phrase)
        if len(keys) >= n and tuple(keys[-n:] if end else keys[:n]) == phrase:
            return n
    return 0


def _all_sales(text: str) -> bool:
    """A bracketed group made of nothing but sales phrases — "(RARE)", "[NWT]"."""
    keys = list(tokens(text))
    if not keys:
        return False
    while keys:
        n = _sales_phrase_at(keys, end=False)
        if not n:
            return False
        keys = keys[n:]
    return True


def strip_sales_tags(text: str | None) -> str | None:
    """A colorway with a reseller's sales tags taken off, or None if that is all
    it was: `"Black (RARE)"` → `"Black"`, `"Navy NEW WITH TAGS"` → `"Navy"`,
    `"RARE"` → None. Only whole bracketed groups and whole phrases at either
    END come off; a word inside a name is left alone."""
    if not text:
        return None
    words: list[str] = []
    for word in text.replace("(", " ( ").replace(")", " ) ").replace("[", " [ ").replace("]", " ] ").split():
        words.append(word)
    # Bracketed groups made only of sales phrases, wherever they sit.
    out: list[str] = []
    i = 0
    while i < len(words):
        if words[i] in ("(", "["):
            close = ")" if words[i] == "(" else "]"
            j = next((k for k in range(i + 1, len(words)) if words[k] == close), None)
            if j is not None and _all_sales(" ".join(words[i + 1:j])):
                i = j + 1
                continue
        out.append(words[i])
        i += 1
    # Whole phrases at either end, and the stray punctuation they leave
    # ("Black - RARE!" → "Black"). Never a bracket: it closes a kept group.
    while out:
        keys = [" ".join(tokens(w)) for w in out]
        if not keys[-1] and out[-1] not in _BRACKETS:
            out.pop()
            continue
        if not keys[0] and out[0] not in _BRACKETS:
            out.pop(0)
            continue
        n = _sales_phrase_at(keys, end=True)
        if n:
            del out[-n:]
            continue
        n = _sales_phrase_at(keys, end=False, phrases=_LEADING_SALES_PHRASES)
        if n:
            del out[:n]
            continue
        break
    cleaned = " ".join(out).replace("( ", "(").replace(" )", ")").replace("[ ", "[").replace(" ]", "]")
    return cleaned or None


#: Receipt spellings of a line the hat record spells another way. melin's
#: order emails called the Odysea "Odyssey" (2024–2025 on the owner's
#: history), while every hat — named from melin's catalog or by the owner —
#: says "Odysea". Six purchase lines matched nothing for that alone.
_MODEL_ALIASES: dict[str, str] = {"odyssey": "odysea"}
#: Words a receipt puts in a model name that identify nothing: "The Shore
#: Hydro" is the Shore line, and no hat record carries the article.
_MODEL_FILLER: frozenset[str] = frozenset({"the"})


@functools.lru_cache(maxsize=4096)
def model_tokens(name: str | None) -> frozenset[str]:
    """`token_set`, with receipt-only spellings folded — for comparing MODEL
    names only. Not folded into `token_set` itself: "the" is a real word in
    series names ("Melin x Hawaii (Explore The Unexplored)" is one on this
    shelf), and only a model comparison may drop it. Cached: the purchase
    matcher's model gate is quadratic."""
    return frozenset(_MODEL_ALIASES.get(t, t) for t in token_set(name)) - _MODEL_FILLER


# How order lines AND marketplace listings spell sizes, mapped to the app's
# vocabulary. Order emails render the variant as the customer sees it
# ("Transit / Classic"), which is title-cased and occasionally abbreviated;
# melin Recap listings carry a size code in publicData ("C", "S", "XL"), and
# `melin_recap._listing_facts` reads it through `normalize_size` too. Two
# readers, so a new spelling added here for one is understood by both.
# `Hat.size` stores the enum value.
_SIZE_ALIASES: dict[str, str] = {
    "classic": "classic",
    "c": "classic",
    "cl": "classic",         # how resellers abbreviate it (Hawaiian Island Creations)
    "standard": "classic",   # the pre-2.0 name for the same size
    "small": "small",
    "s": "small",
    "sm": "small",
    "xlarge": "x_large",
    "x_large": "x_large",
    "xl": "x_large",
    "extralarge": "x_large",
    "onesize": None,         # travel cases and accessories, not a hat size
}


def normalize_size(raw: str | None) -> str | None:
    """"Classic" / "X-Large" / "C" -> the `Hat.size` value, or None.

    None means "no usable size on this line" and is not a failure: matching
    treats it as a wildcard, which is the pre-2.19 behavior. Returning a
    made-up value instead would be worse than returning nothing, because a
    wrong size actively prevents the correct match rather than merely failing
    to sharpen it.
    """
    if not raw:
        return None
    key = raw.strip().lower().replace("-", "").replace(" ", "").replace("_", "")
    return _SIZE_ALIASES.get(key)
