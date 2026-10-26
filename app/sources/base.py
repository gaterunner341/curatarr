"""Common types for list sources."""
from dataclasses import asdict, dataclass

import httpx

from .. import config

USER_AGENT = f"{config.APP_NAME}/{config.VERSION} (+https://github.com/gaterunner341/curatarr)"


class SourceError(Exception):
    pass


@dataclass
class MediaRef:
    """A movie or show identified by any combination of external ids."""
    media_type: str | None = None   # "movie", "show" or None when unknown
    title: str = ""
    year: int | None = None
    imdb: str | None = None
    tmdb: int | None = None
    tvdb: int | None = None

    def key(self) -> str:
        if self.imdb:
            return f"imdb:{self.imdb}"
        if self.tmdb:
            return f"tmdb:{self.media_type or ''}:{self.tmdb}"
        if self.tvdb:
            return f"tvdb:{self.tvdb}"
        return f"title:{self.title.lower()}|{self.year}"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SourceContext:
    settings: dict
    http: httpx.Client
    media_type: str   # library type the list is being matched against


def year_of(date: str | None) -> int | None:
    if date and len(date) >= 4 and date[:4].isdigit():
        return int(date[:4])
    return None


def to_int(value) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
