from pydantic import BaseModel

from headroom.schemas.hat import ColorTag


class SearchResult(BaseModel):
    id: int
    display_id: str | None
    case_display_id: str | None
    photo_path: str | None
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
