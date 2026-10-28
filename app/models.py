"""Pydantic models shared by the API, the sync engine and YAML import/export."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SourceType = Literal[
    "tmdb_list",
    "tmdb_collection",
    "tmdb_chart",
    "tmdb_discover",
    "imdb_list",
    "imdb_chart",
    "trakt_list",
    "trakt_chart",
    "mdblist",
    "static",
    "plex_filter",
]

CollectionMode = Literal["default", "hide", "hideItems", "showItems"]
CollectionOrder = Literal["custom", "release", "alpha"]


class Source(BaseModel):
    type: SourceType
    value: str = ""
    limit: int | None = Field(default=None, ge=1, le=5000)

    @field_validator("value")
    @classmethod
    def strip_value(cls, v: str) -> str:
        return v.strip()


class Exclusion(BaseModel):
    """A title kept out of a collection: ``plex:<ratingKey>``, ``tt…``, ``tmdb:…`` or ``tvdb:…``."""
    id: str = Field(min_length=1)
    title: str = ""


# Content ratings from youngest to oldest audience. US movie and TV ratings that
# mean roughly the same share a level, so a cap works for both kinds of library.
RATING_LEVELS = {
    "TV-Y": 0, "G": 1, "TV-Y7": 1, "TV-G": 1, "PG": 2, "TV-PG": 2,
    "PG-13": 3, "TV-14": 3, "R": 4, "TV-MA": 4, "NC-17": 5,
}


def rating_level(rating: str | None) -> int | None:
    """Level of a Plex content rating, or None when it's unrated or not a US rating."""
    if not rating:
        return None
    return RATING_LEVELS.get(rating.split("/")[-1].strip().upper())


class CollectionConfig(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["collection", "playlist"] = "collection"
    library: str = ""            # Plex library title (portable across servers)
    section_id: str = ""         # Plex library section id (preferred when valid)
    # Playlists can draw from several libraries (movies and TV together).
    libraries: list[str] = []
    section_ids: list[str] = []
    sources: list[Source] = Field(min_length=1)
    sync_mode: Literal["sync", "append"] = "sync"
    order: CollectionOrder = "custom"
    summary: str = ""
    sort_title: str = ""
    labels: list[str] = []
    collection_mode: CollectionMode = "default"
    poster_url: str = ""
    art_url: str = ""
    poster_file: str = ""        # set by the upload endpoint, not by users
    art_file: str = ""
    item_limit: int = Field(default=0, ge=0)
    min_items: int = Field(default=1, ge=0)
    delete_below_min: bool = False
    promote_home: bool = False
    promote_shared: bool = False
    promote_recommended: bool = False
    # Home screen calendar: when on, the promote_* spots above are only used
    # between promote_start and promote_end (YYYY-MM-DD), optionally every year.
    promote_window: bool = False
    promote_start: str = ""
    promote_end: str = ""
    promote_yearly: bool = True
    # With a calendar: the Plex collection only exists during the window. It is
    # created when the window opens and deleted from Plex after it closes.
    seasonal_only: bool = False
    schedule: str = ""           # cron expression; blank uses the global default
    request_missing: bool = False
    enabled: bool = True
    holiday: str = ""            # key from app.holidays when created from the Holidays page
    exclude: list[Exclusion] = []
    max_rating: str = ""         # content rating cap, e.g. "PG-13"; blank = no cap
    drop_unrated: bool = False   # with a cap: also leave out unrated titles

    @field_validator("max_rating")
    @classmethod
    def check_rating(cls, v: str) -> str:
        v = v.strip().upper()
        if v and v not in RATING_LEVELS:
            raise ValueError(f"Unknown content rating '{v}'")
        return v

    @field_validator("name", "summary", "sort_title", "schedule", "poster_url", "art_url")
    @classmethod
    def strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("labels")
    @classmethod
    def clean_labels(cls, v: list[str]) -> list[str]:
        return [label.strip() for label in v if label and label.strip()]

    @model_validator(mode="after")
    def check_playlist(self) -> "CollectionConfig":
        if self.kind == "playlist":
            if not self.section_ids and self.section_id:
                self.section_ids, self.libraries = [self.section_id], [self.library]
            if self.section_ids:     # the first library stands in where one is expected
                self.section_id = self.section_ids[0]
                self.library = self.libraries[0] if self.libraries else self.library
            # Home screen spots and seasons are collection features.
            self.promote_home = self.promote_shared = self.promote_recommended = False
            self.promote_window = self.seasonal_only = False
        return self

    @model_validator(mode="after")
    def check_window(self) -> "CollectionConfig":
        if self.promote_window:
            try:
                start = date.fromisoformat(self.promote_start)
                end = date.fromisoformat(self.promote_end)
            except ValueError:
                raise ValueError("Home screen calendar needs a start and end date")
            if not self.promote_yearly and end < start:
                raise ValueError("Home screen calendar ends before it starts")
        return self

    def promotion_active(self, today: date) -> bool:
        """Whether the home screen calendar (if any) allows promotion on ``today``."""
        if not self.promote_window:
            return True
        start = date.fromisoformat(self.promote_start)
        end = date.fromisoformat(self.promote_end)
        if not self.promote_yearly:
            return start <= today <= end
        day = (today.month, today.day)
        first, last = (start.month, start.day), (end.month, end.day)
        if first <= last:
            return first <= day <= last
        return day >= first or day <= last      # wraps over New Year, e.g. Dec 15 - Jan 5

    def off_season(self, today: date) -> bool:
        """True when the collection should not exist in Plex today."""
        return self.promote_window and self.seasonal_only and not self.promotion_active(today)

    def allows_rating(self, rating: str | None) -> bool:
        """Whether a title with this content rating fits under ``max_rating``."""
        if not self.max_rating:
            return True
        level = rating_level(rating)
        if level is None:
            return not self.drop_unrated
        return level <= RATING_LEVELS[self.max_rating]

    def promotion_flags(self, today: date) -> tuple[bool, bool, bool]:
        """(recommended, home, shared) to apply today."""
        active = self.promotion_active(today)
        return (self.promote_recommended and active, self.promote_home and active,
                self.promote_shared and active)


class PreviewRequest(BaseModel):
    section_id: str = ""
    library: str = ""
    section_ids: list[str] = []      # a playlist's libraries
    sources: list[Source] = Field(min_length=1)
    item_limit: int = 0
