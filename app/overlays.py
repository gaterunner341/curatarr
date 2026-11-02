"""Poster overlays: ribbons drawn on the posters of the titles in a collection.

Before Curatarr first changes a title's poster it keeps the original in
``/config/overlays``. Posters are only redrawn when what should be on them
changes, or when Plex replaces the artwork (an agent refresh or a poster you
picked; that becomes the new original). When a title no longer needs an
overlay, its original poster is put back.
"""
import hashlib
import io
import json
import logging
import math
import threading

from PIL import Image, ImageDraw, ImageFilter

from . import config, db, plex as plexmod
from .models import CollectionConfig
from .plex import Plex, PlexError
from .posters import PosterError, font, hex_rgb

log = logging.getLogger(__name__)

LABEL = "Curatarr Overlay"        # on every title whose poster carries an overlay
ORIGINALS = config.CONFIG_DIR / "overlays"
RIBBON_FONTS = ["arialbd.ttf", "DejaVuSans-Bold.ttf", "segoeuib.ttf"]
STYLE_VERSION = 1                 # bump when the drawing changes, so posters are redrawn
W = 1000                          # posters are drawn at this width

_lock = threading.Lock()
_again = threading.Event()


class OverlayError(Exception):
    pass


# --- drawing -------------------------------------------------------------------------

def _ribbon(img: Image.Image, spec: dict, slot: int) -> None:
    """A diagonal band across a top corner; ``slot`` stacks ribbons sharing a corner."""
    w, h = img.size
    thick = w * 0.10
    # Distance from the corner, along each edge, to where the band's middle crosses it.
    reach = w * 0.30 + slot * thick * 1.5
    length = int(reach * math.sqrt(2) * 2)
    strip = Image.new("RGBA", (length, int(thick)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(strip)
    draw.rectangle([0, 0, length, thick], fill=hex_rgb(spec["color"]))
    edge = max(2, int(thick * 0.05))       # a fine darker line along both edges
    draw.rectangle([0, 0, length, edge], fill=(0, 0, 0, 40))
    draw.rectangle([0, thick - edge, length, thick], fill=(0, 0, 0, 40))
    text = spec.get("text") or ""
    if text:
        room = (reach * math.sqrt(2) - thick) * 0.92     # visible length of the band's middle
        size = int(thick * 0.58)
        while size > 8:
            fnt = font(RIBBON_FONTS, size)
            if draw.textlength(text, font=fnt) <= room:
                break
            size -= 2
        draw.text((length / 2, thick / 2), text, font=fnt, fill=hex_rgb(spec["text_color"]), anchor="mm")
    angle = -45 if spec["corner"] == "top-right" else 45
    band = strip.rotate(angle, expand=True, resample=Image.BICUBIC)
    cx = w - reach / 2 if spec["corner"] == "top-right" else reach / 2
    cy = reach / 2
    pos = (int(cx - band.width / 2), int(cy - band.height / 2))
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 110), (pos[0], pos[1] + int(thick * 0.08)), band.getchannel("A"))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(thick * 0.12)))
    img.alpha_composite(band, pos)


# Rating sources are shown as text in each site's colour, not with their logos.
PROVIDERS = {"imdb": ("IMDb", "#f5c518"), "themoviedb": ("TMDB", "#01b4e4"), "rottentomatoes": ("RT", "#fa320a")}


def _pill(img: Image.Image, x: float, y: float, h: float, parts: list[tuple[str, str]], right: bool = False) -> float:
    """A rounded dark badge with coloured text parts; returns its width. ``right`` anchors x at its right edge."""
    draw = ImageDraw.Draw(img)
    fnt = font(RIBBON_FONTS, int(h * 0.56))
    gap = h * 0.22
    widths = [draw.textlength(text, font=fnt) for text, _ in parts]
    width = sum(widths) + gap * (len(parts) - 1) + h * 0.8
    left = x - width if right else x
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle([left, y, left + width, y + h], radius=h * 0.28, fill=(10, 10, 12, 215),
                                            outline=(255, 255, 255, 90), width=max(2, int(h * 0.04)))
    img.alpha_composite(layer)
    tx = left + h * 0.4
    for (text, color), w in zip(parts, widths):
        draw.text((tx, y + h / 2), text, font=fnt, fill=hex_rgb(color), anchor="lm")
        tx += w + gap
    return width


def _badges(img: Image.Image, spec: dict) -> None:
    """Quality badges along the bottom left, the rating badge at the bottom right."""
    w, h = img.size
    pill = w * 0.075
    margin = w * 0.04
    y = h - margin - pill
    x = margin
    for label in spec.get("quality") or []:
        x += _pill(img, x, y, pill, [(label, "#ffffff")]) + pill * 0.25
    rating = spec.get("rating")
    if rating:
        name, color = PROVIDERS.get(rating["source"], (rating["source"], "#ffffff"))
        _pill(img, w - margin, y, pill, [(name, color), (rating["value"], "#ffffff")], right=True)


def render(original: bytes, specs: list[dict]) -> bytes:
    """The original poster with ``specs`` drawn on it, as a JPEG."""
    try:
        img = Image.open(io.BytesIO(original)).convert("RGBA")
    except OSError as exc:
        raise OverlayError(f"Plex's poster isn't a readable image: {exc}") from exc
    if img.width != W:
        img = img.resize((W, round(img.height * W / img.width)), Image.LANCZOS)
    corners: dict[str, int] = {}
    for spec in specs:
        if spec["kind"] == "ribbon":
            slot = corners.get(spec["corner"], 0)
            corners[spec["corner"]] = slot + 1
            _ribbon(img, spec, slot)
        elif spec["kind"] == "badges":
            _badges(img, spec)
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue()


def sample_poster() -> bytes:
    """A plain poster to preview overlays on when there's no Plex poster to use."""
    from .posters import gradient
    img = gradient("#2b3445", "#0c0f14", (W, 1500))
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=90)
    return out.getvalue()


def preview(specs: list[dict], plex: Plex | None = None, thumb: str = "") -> bytes:
    if plex and thumb:
        try:
            return render(plex.image(thumb)[0], specs)
        except (PlexError, OverlayError):
            pass                     # fall back to the plain sample
    return render(sample_poster(), specs)


# --- what goes where ---------------------------------------------------------------

def ribbon_spec(cfg: CollectionConfig) -> dict | None:
    if cfg.kind != "collection" or not cfg.ribbon.enabled:
        return None
    return {"kind": "ribbon", **cfg.ribbon.model_dump(exclude={"enabled"})}


def badge_settings(cfg: CollectionConfig) -> dict | None:
    if cfg.kind != "collection" or not (cfg.badges.quality or cfg.badges.rating):
        return None
    return cfg.badges.model_dump()


def needed() -> bool:
    """Whether an overlay pass has anything to do (overlays wanted, or ones to remove)."""
    if db.overlay_rows():
        return True
    configs = [CollectionConfig(**r["config"]) for r in db.list_collections()]
    return any(ribbon_spec(c) or badge_settings(c) for c in configs)


RESOLUTIONS = {"4k": "4K", "2160": "4K", "1080": "1080P", "720": "720P", "576": "SD", "480": "SD", "sd": "SD"}
RES_ORDER = ["4K", "1080P", "720P", "SD"]


def media_key(item: dict) -> str:
    """Changes when a title's files change, so cached quality info is refreshed."""
    return ",".join(str(m.get("id")) for m in item.get("Media") or []) or str(item.get("updatedAt") or "")


def quality_labels(item: dict) -> list[str]:
    """["4K", "DV" or "HDR", "ATMOS"] for the best version of a movie (detailed metadata)."""
    best, best_rank = None, len(RES_ORDER)
    for media in item.get("Media") or []:
        res = RESOLUTIONS.get(str(media.get("videoResolution") or "").lower())
        rank = RES_ORDER.index(res) if res else len(RES_ORDER)
        if best is None or rank < best_rank:
            best, best_rank = media, rank
    if not best:
        return []
    labels = [RES_ORDER[best_rank]] if best_rank < len(RES_ORDER) else []
    streams = [st for part in best.get("Part") or [] for st in part.get("Stream") or []]
    video = [st for st in streams if st.get("streamType") == 1]
    if any(st.get("DOVIPresent") for st in video):
        labels.append("DV")
    elif any(st.get("colorTrc") in ("smpte2084", "arib-std-b67") or "HDR" in (st.get("displayTitle") or "")
             for st in video):
        labels.append("HDR")
    audio = " ".join(f"{st.get('displayTitle', '')} {st.get('extendedDisplayTitle', '')}"
                     for st in streams if st.get("streamType") == 2)
    if "atmos" in audio.lower():
        labels.append("ATMOS")
    return labels


def rating_badge(item: dict, source: str, minimum: float = 0) -> dict | None:
    """{source, value} from the ratings Plex shows: audience or critic, out of 10."""
    value = item.get("audienceRating" if source == "audience" else "rating")
    image = item.get("audienceRatingImage" if source == "audience" else "ratingImage") or ""
    if value is None:
        return None
    value = float(value)
    if value < minimum:
        return None
    provider = image.split("://", 1)[0] if "://" in image else ""
    text = f"{round(value * 10)}%" if provider == "rottentomatoes" else f"{value:.1f}"
    return {"source": provider or ("audience" if source == "audience" else "critic"), "value": text}


def _wanted(plex: Plex) -> dict[str, dict]:
    """rating key -> what every title that should carry overlays needs:
    {ribbons, badges (merged settings), item (Plex metadata), section_id, type, thumb}."""
    wanted: dict[str, dict] = {}
    for row in db.list_collections():
        cfg = CollectionConfig(**row["config"])
        ribbon, badges = ribbon_spec(cfg), badge_settings(cfg)
        if not (ribbon or badges) or not row.get("plex_rating_key"):
            continue
        try:
            items = plex.collection_raw(row["plex_rating_key"])
        except PlexError as exc:
            if exc.status != 404:
                raise
            continue
        for item in items:
            rk = str(item["ratingKey"])
            entry = wanted.setdefault(rk, {
                "ribbons": [], "badges": None, "item": item, "section_id": cfg.section_id,
                "type": item.get("type") or "movie", "thumb": item.get("thumb") or ""})
            if ribbon:
                entry["ribbons"].append({**ribbon, "collection": row["id"]})
            if badges:
                merged = entry["badges"] or {"quality": False, "rating": "", "rating_min": 0}
                merged["quality"] = merged["quality"] or badges["quality"]
                if badges["rating"] and not merged["rating"]:      # the first collection's choice wins
                    merged["rating"], merged["rating_min"] = badges["rating"], badges["rating_min"]
                entry["badges"] = merged
    return wanted


def _specs(plex: Plex, rk: str, entry: dict, row: dict | None) -> tuple[list[dict], str, list]:
    """The overlays to draw on one title, plus its media key and quality labels to cache."""
    specs = sorted(entry["ribbons"], key=lambda s: s["collection"])
    settings, item = entry["badges"], entry["item"]
    key, quality, detail = media_key(item), [], None
    if settings and settings["quality"] and entry["type"] == "movie":
        if row and row.get("media_key") == key and row.get("media"):
            quality = json.loads(row["media"])
        else:                       # HDR and Atmos are only in the detailed metadata
            detail = plex.item(rk) or item
            quality = quality_labels(detail)
    rating = None
    if settings and settings["rating"]:
        field = "audienceRating" if settings["rating"] == "audience" else "rating"
        if item.get(field) is None:  # some Plex versions leave ratings out of collection listings
            detail = detail or plex.item(rk) or item
            item = {**item, **{k: detail.get(k) for k in (field, f"{field}Image")}}
        rating = rating_badge(item, settings["rating"], settings["rating_min"])
    if quality or rating:
        specs.append({"kind": "badges", "quality": quality, "rating": rating})
    return specs, key, quality


def signature(specs: list[dict]) -> str:
    return hashlib.sha1(json.dumps([STYLE_VERSION, specs], sort_keys=True).encode()).hexdigest()


# --- applying ------------------------------------------------------------------------

def _original_path(rating_key: str):
    return ORIGINALS / f"{rating_key}.jpg"


def _apply_one(plex: Plex, rk: str, entry: dict, row: dict | None) -> bool | None:
    """Draw a title's overlays if they changed.

    Returns True when its poster was uploaded, False when it was already up to
    date, and None when there's nothing to draw on it.
    """
    specs, key, quality = _specs(plex, rk, entry, row)
    if not specs:                   # e.g. badges only, and nothing to show for this title
        if row:
            _restore_one(plex, rk, row)
        return None
    sig = signature(specs)
    thumb = entry["thumb"]
    replaced = not row or row["applied_thumb"] != thumb      # first time, or Plex changed the poster
    if not replaced and row["signature"] == sig:
        return False
    path = _original_path(rk)
    if replaced or not path.is_file():
        if not thumb:
            return False
        original, _ = plex.image(thumb)
        ORIGINALS.mkdir(parents=True, exist_ok=True)
        path.write_bytes(original)
    plex.upload_image(rk, "poster", data=render(path.read_bytes(), specs))
    new_thumb = (plex.item(rk) or {}).get("thumb") or ""
    db.save_overlay(rk, entry["section_id"], entry["type"], sig, new_thumb, key, quality)
    if not row:
        try:
            plex.set_item_label(entry["section_id"], rk, entry["type"], LABEL, True)
        except PlexError as exc:
            log.debug("Could not label %s: %s", rk, exc)
    return True


def _restore_one(plex: Plex, rk: str, row: dict) -> bool:
    """Put a title's original poster back. Returns True when a poster was uploaded."""
    path = _original_path(rk)
    item = plex.item(rk)
    uploaded = False
    if item and path.is_file() and item.get("thumb") == row["applied_thumb"]:
        plex.upload_image(rk, "poster", data=path.read_bytes())
        uploaded = True
    if item:
        try:
            plex.set_item_label(row["section_id"], rk, row["item_type"], LABEL, False)
        except PlexError as exc:
            log.debug("Could not unlabel %s: %s", rk, exc)
    path.unlink(missing_ok=True)
    db.delete_overlay(rk)
    return uploaded


def apply_all(remove_all: bool = False) -> dict:
    """Bring every overlaid poster up to date; with ``remove_all``, restore them all.

    Only one pass runs at a time; a request during a pass makes it run once more.
    """
    if not _lock.acquire(blocking=False):
        _again.set()
        return {"queued": True}
    try:
        while True:
            _again.clear()
            result = _pass(remove_all)
            if not _again.is_set():
                return result
    finally:
        _lock.release()


def _pass(remove_all: bool) -> dict:
    counts = {"drawn": 0, "restored": 0, "unchanged": 0, "nothing": 0, "errors": 0}
    with plexmod.from_settings(db.get_settings()) as plex:
        wanted = {} if remove_all else _wanted(plex)
        rows = db.overlay_rows()
        for rk, entry in wanted.items():
            try:
                done = _apply_one(plex, rk, entry, rows.get(rk))
                counts["drawn" if done else "unchanged" if done is False else "nothing"] += 1
            except (PlexError, OverlayError, PosterError, OSError) as exc:
                counts["errors"] += 1
                log.warning("Overlay for %s failed: %s", rk, exc)
        for rk, row in rows.items():
            if rk in wanted:
                continue
            try:
                _restore_one(plex, rk, row)
                counts["restored"] += 1
            except (PlexError, OSError) as exc:
                counts["errors"] += 1
                log.warning("Restoring the poster of %s failed: %s", rk, exc)
    log.info("Overlays: %d title(s) with overlays: %d drawn, %d unchanged, %d with nothing to show "
             "(e.g. no rating); %d restored, %d failed", len(wanted), counts["drawn"], counts["unchanged"],
             counts["nothing"], counts["restored"], counts["errors"])
    return counts
