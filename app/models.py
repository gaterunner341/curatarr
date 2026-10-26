"""Pydantic models shared by the API, the sync engine and YAML import/export."""
from typing import Literal

from pydantic import BaseModel, Field, field_validator

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


class CollectionConfig(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    library: str = ""            # Plex library title (portable across servers)
    section_id: str = ""         # Plex library section id (preferred when valid)
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
    schedule: str = ""           # cron expression; blank uses the global default
    request_missing: bool = False
    enabled: bool = True

    @field_validator("name", "summary", "sort_title", "schedule", "poster_url", "art_url")
    @classmethod
    def strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("labels")
    @classmethod
    def clean_labels(cls, v: list[str]) -> list[str]:
        return [label.strip() for label in v if label and label.strip()]


class PreviewRequest(BaseModel):
    section_id: str = ""
    library: str = ""
    sources: list[Source] = Field(min_length=1)
    item_limit: int = 0
