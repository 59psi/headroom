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
    colors: list[ColorTag]
