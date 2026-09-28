from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from headroom.schemas.hat import ColorTag


class ColorScope(StrEnum):
    """Which swatches a color term may match.

    A query parameter on two routes; typed so a typo answers 422 instead of
    quietly searching the default scope — `?color_scope=acent` used to return
    the major-color matches under a request that asked for accents.
    """

    major = "major"    # the hat's own colors (the default)
    accent = "accent"  # logos, piping, underbrims
    all = "all"


#: Longest search string either search route accepts. Terms are AND-ed into
#: one SQL expression per term, and a thousand of them outgrew SQLite's
#: expression-depth limit — a 500 and an `error.unhandled` row from a query
#: string. Two hundred characters is far past any real search.
MAX_QUERY_LENGTH = 200


class SearchResult(BaseModel):
    """A hat as the Search and Duplicates pages render it.

    `from_attributes=True`, like `HatRead`: every field here is a column or a
    `@property` on `Hat` (`display_id`, `case_display_id`, `room_id`,
    `room_name`), and `ColorTag` already validates from the ORM row. The route
    used to hand-copy fifteen attributes into a dict — a response shape
    nothing declares, which `tests/test_api_contract.py` now refuses.
    """

    id: int
    display_id: str | None
    case_display_id: str | None
    photo_path: str | None
    thumb_path: str | None = None
    style: str
    condition: str
    size: str
    is_beanie: bool
    brand: str | None
    model_name: str | None
    # Projected so the shared hat filter bar can filter on it. The Search page
    # applies `matchesHatFilters` to these rows client-side, so a field the
    # filter reads but the projection omits shows a working control that
    # silently matches nothing.
    construction: str | None = None
    #: A text search matches the colorway, so a row can be listed for it —
    #: and the Search page renders the Hats tab's own row, which shows it.
    #: Without it here a hat matched on "Coronado" listed no word of why.
    colorway: str | None = None
    colors: list[ColorTag]
    room_id: int | None
    room_name: str | None

    model_config = ConfigDict(from_attributes=True)


class ColorSearchResult(SearchResult):
    """A SearchResult ranked by perceptual color closeness.

    `distance` is the raw CIEDE2000 between the search color and the swatch
    that matched — it is NOT the value the list is sorted by, because a match
    on a hat's accent counts for less than one on its main color. Ordering
    comes from the server; `matched_rank` is what lets the UI say why a nearer
    number sits below a further one.
    """

    matched_hex: str
    distance: float
    matched_rank: int


class DuplicateGroupRead(BaseModel):
    """A set of hats that look like the same hat entered more than once.

    `confidence` is "exact" when every identity field agrees, "likely" when the
    model and size match and the colorway is MISSING on one side — usually a
    twin that hasn't been analyzed yet, so it has no colorway to compare.
    Colorways that actively disagree are never grouped, or every normal shelf
    (one line in three colors) would read as a mistake.
    """

    key: str
    confidence: str
    label: str
    hats: list[SearchResult]
