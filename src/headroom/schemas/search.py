from pydantic import BaseModel

from headroom.schemas.hat import ColorTag


class SearchResult(BaseModel):
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
    colors: list[ColorTag]
    room_id: int | None
    room_name: str | None

    model_config = {"protected_namespaces": ()}


class ColorSearchResult(SearchResult):
    """A SearchResult ranked by perceptual color closeness."""

    matched_hex: str
    distance: float


class DuplicateGroupRead(BaseModel):
    """A set of hats that look like the same hat entered more than once.

    `confidence` is "exact" when every identity field agrees, "likely" when the
    model and size match but the colourway doesn't — usually a twin that hasn't
    been analysed yet, so it has no colourway to compare.
    """

    key: str
    confidence: str
    label: str
    hats: list[SearchResult]
