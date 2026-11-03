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
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from . import config, db, plex as plexmod
from .models import CollectionConfig
from .plex import Plex, PlexError
from .posters import PosterError, font, hex_rgb

log = logging.getLogger(__name__)

LABEL = "Curatarr Overlay"        # on every title whose poster carries an overlay
ORIGINALS = config.CONFIG_DIR / "overlays"
RIBBON_FONTS = ["arialbd.ttf", "DejaVuSans-Bold.ttf", "segoeuib.ttf"]     # badges, and the "sans" ribbon font
# Ribbon fonts: key -> (name, font files to look for). All are free fonts installed in the
# Docker image; only the ones found are offered.
FONTS = {
    "sans": ("Sans bold", RIBBON_FONTS),
    "condensed": ("Condensed bold", ["RobotoCondensed-Bold.ttf", "LiberationSansNarrow-Bold.ttf", "ARIALNB.TTF"]),
    "roboto": ("Roboto bold", ["Roboto-Bold.ttf"]),
    "open-sans": ("Open Sans bold", ["OpenSans-Bold.ttf", "OpenSans-ExtraBold.ttf"]),
    "lato": ("Lato black", ["Lato-Black.ttf", "Lato-Heavy.ttf"]),
    "serif": ("Serif bold", ["DejaVuSerif-Bold.ttf", "georgiab.ttf"]),
    "mono": ("Mono bold", ["DejaVuSansMono-Bold.ttf", "consolab.ttf"]),
}
SIZES = {"small": 0.8, "medium": 1.0, "large": 1.25, "xlarge": 1.5}     # ribbon thickness
STYLE_VERSION = 5                 # bump when the drawing changes, so posters are redrawn
BADGE_SIZES = {"small": 0.75, "medium": 1.0, "large": 1.3, "xlarge": 1.6}
W = 1000                          # posters are drawn at this width

_lock = threading.Lock()
_again = threading.Event()

# What the current (or last) pass is doing, for the web UI's progress indicator.
progress: dict = {"running": False, "phase": "", "done": 0, "total": 0, "drawn": 0, "restored": 0,
                  "errors": 0, "started": None, "finished": None}


class OverlayError(Exception):
    pass


# --- drawing -------------------------------------------------------------------------

# Rotation of the band, and which edges it crosses, for each corner. Text runs left to right.
CORNERS = {"top-right": (-45, "right", "top"), "top-left": (45, "left", "top"),
           "bottom-right": (45, "right", "bottom"), "bottom-left": (-45, "left", "bottom")}


def _ribbon(img: Image.Image, spec: dict, slot: int) -> float:
    """A diagonal band across a corner; ``slot`` stacks ribbons sharing a corner.

    Returns how far from the corner, along each edge, the band's outer edge reaches.
    """
    w, h = img.size
    scale = SIZES.get(spec.get("size") or "medium", 1.0)
    picture = _ribbon_image(spec.get("image") or "")
    if picture is not None:                # a built-in's ribbon picture, made for the bottom-right corner
        side = int(w * 0.42 * scale)
        picture = picture.resize((side, side), Image.LANCZOS)
        img.alpha_composite(picture, (w - side, h - side))
        return float(side)
    # Kometa-like proportions: a thick band close to the corner.
    thick = w * 0.19 * scale
    # Distance from the corner, along each edge, to where the band's middle crosses it.
    reach = w * 0.30 * scale + slot * thick * 1.5
    length = int(reach * math.sqrt(2) * 2 + thick * 2)
    strip = Image.new("RGBA", (length, int(thick)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(strip)
    draw.rectangle([0, 0, length, thick], fill=hex_rgb(spec["color"]))
    edge = max(2, int(thick * 0.04))       # a fine darker line along both edges
    draw.rectangle([0, 0, length, edge], fill=(0, 0, 0, 40))
    draw.rectangle([0, thick - edge, length, thick], fill=(0, 0, 0, 40))
    angle, side, end = CORNERS.get(spec["corner"], CORNERS["top-right"])
    text = (spec.get("text") or "").strip()
    if text:
        _ribbon_text(draw, text, spec, length, thick, reach, toward_corner_is_top=end == "top")
    band = strip.rotate(angle, expand=True, resample=Image.BICUBIC)
    cx = w - reach / 2 if side == "right" else reach / 2
    cy = reach / 2 if end == "top" else h - reach / 2
    pos = (int(cx - band.width / 2), int(cy - band.height / 2))
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 110), (pos[0], pos[1] + int(thick * 0.08)), band.getchannel("A"))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(thick * 0.12)))
    img.alpha_composite(band, pos)
    return reach + thick * 0.75          # the band's half-width, measured along an edge


RIBBON_IMAGES = Path(__file__).parent / "static" / "ribbons"


def _ribbon_image(key: str) -> Image.Image | None:
    """A ribbon picture by name, with a plain white background made see-through. None when there's
    no such picture (the ribbon is then drawn with its text)."""
    path = RIBBON_IMAGES / f"{key}.png"
    if not key or not path.is_file():
        return None
    picture = Image.open(path).convert("RGBA")
    if picture.getextrema()[3][0] == 255:          # no transparency in the file: drop the white
        picture.putdata([(r, g, b, 0) if min(r, g, b) >= 240 else (r, g, b, a) for r, g, b, a in picture.getdata()])
    return picture


def _fit(draw: ImageDraw.ImageDraw, text: str, names: list[str], size: int, room: float):
    """The font size (and font) at which ``text`` fits in ``room``, starting from ``size``."""
    while size > 8:
        fnt = _font(names, size)
        if draw.textlength(text, font=fnt) <= room:
            return size, fnt
        size -= 2
    return size, _font(names, size)


def _ribbon_text(draw: ImageDraw.ImageDraw, text: str, spec: dict, length: int, thick: float, reach: float,
                 toward_corner_is_top: bool) -> None:
    """Ribbon text as big as the band allows. Text that would come out small on one line is split
    over two, like Kometa's ribbons: the first part on top and a little bigger, the rest below it."""
    names = FONTS.get(spec.get("font") or "sans", FONTS["sans"])[1]
    colour = hex_rgb(spec["text_color"])
    mid = length / 2

    def room(y: float) -> float:
        # Visible length of a text line centred ``y`` down the band. Lines further from the
        # corner are longer; the top of the text faces the corner in the top corners.
        away = (y - thick / 2) if toward_corner_is_top else (thick / 2 - y)
        return max(0.0, (reach * math.sqrt(2) + 2 * away) * 0.86)

    size, fnt = _fit(draw, text, names, int(thick * 0.62), room(thick / 2))
    words = text.split()
    if size >= thick * 0.45 or len(words) < 2:
        draw.text((mid, thick / 2), text, font=fnt, fill=colour, anchor="mm")
        return
    top, bottom = thick * 0.31, thick * 0.73
    # Two lines: the split that gives the biggest text, with the first line a little bigger.
    best = None
    for i in range(1, len(words)):
        first, second = " ".join(words[:i]), " ".join(words[i:])
        s1, _ = _fit(draw, first, names, int(thick * 0.46), room(top))
        s2, _ = _fit(draw, second, names, int(thick * 0.37), room(bottom))
        score = min(s1, s2 * 1.25)
        if best is None or score > best[0]:
            best = (score, first, s1, second, s2)
    _, first, s1, second, s2 = best
    s2 = min(s2, int(s1 * 0.82))                 # the second line stays smaller than the first
    draw.text((mid, top), first, font=_font(names, s1), fill=colour, anchor="mm")
    draw.text((mid, bottom), second, font=_font(names, s2), fill=colour, anchor="mm")


def _font(names: list[str], size: int):
    """A ribbon font, falling back to the default when that font isn't installed."""
    try:
        return font(names, size)
    except PosterError:
        return font(RIBBON_FONTS, size)


def available_fonts() -> list[dict]:
    """The ribbon fonts installed here: [{key, name}]."""
    out = []
    for key, (name, names) in FONTS.items():
        try:
            font(names, 12)
        except PosterError:
            continue
        out.append({"key": key, "name": name})
    return out


# Rating sources are shown as text in each site's colour, not with their logos.
PROVIDERS = {"imdb": ("IMDb", "#f5c518"), "themoviedb": ("TMDB", "#01b4e4"), "rottentomatoes": ("RT", "#fa320a")}


def _pill(img: Image.Image, x: float, y: float, h: float, parts: list[tuple[str, str]], right: bool = False,
          measure: bool = False) -> float:
    """A rounded dark badge with coloured text parts; returns its width.

    ``right`` anchors x at its right edge; ``measure`` only returns the width.
    """
    draw = ImageDraw.Draw(img)
    fnt = font(RIBBON_FONTS, int(h * 0.56))
    gap = h * 0.22
    widths = [draw.textlength(text, font=fnt) for text, _ in parts]
    width = sum(widths) + gap * (len(parts) - 1) + h * 0.8
    if measure:
        return width
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


def _badges(img: Image.Image, spec: dict, clear: dict[str, float] | None = None) -> None:
    """Quality badges along the bottom left, the rating badge at the bottom right.

    ``clear`` is how far a ribbon in a bottom corner reaches along the bottom
    edge on each side; that side's badges move inward past it.
    """
    w, h = img.size
    clear = clear or {}
    if spec.get("tv_icon"):              # the icon shows the rating already
        spec = {**spec, "content_rating": ""}
    pill = w * 0.09 * BADGE_SIZES.get(spec.get("size") or "medium", 1.0)
    margin = w * 0.04
    y = h - margin - pill
    # A badge's bottom sits ``margin`` above the edge, so it clears the band that much sooner.
    x = max(margin, clear.get("left", 0) - margin)
    if spec.get("content_rating"):
        x += _pill(img, x, y, pill, [(spec["content_rating"], "#f5d77a")]) + pill * 0.25
    for label in spec.get("quality") or []:
        x += _pill(img, x, y, pill, [(label, "#ffffff")]) + pill * 0.25
    rating = spec.get("rating")
    if rating:
        name, color = PROVIDERS.get(rating["source"], (rating["source"], "#ffffff"))
        parts = [(name, color), (rating["value"], "#ffffff")]
        right = w - max(margin, clear.get("right", 0) - margin)
        if right - _pill(img, 0, 0, pill, parts, measure=True) < x:
            # No room beside the quality badges: one row up, where a ribbon needs less room.
            y -= pill * 1.3
            right = w - max(margin, clear.get("right", 0) - margin - pill * 1.3)
        _pill(img, right, y, pill, parts, right=True)


TV_ICONS = Path(__file__).parent / "static" / "tvratings"


def tv_icon_name(rating: str | None) -> str:
    """The TV rating icon for a content rating ("TV-14"), or "" when there's none for it."""
    name = content_rating_label(rating).upper()
    return name if name.startswith("TV-") and (TV_ICONS / f"{name}.png").is_file() else ""


def _tv_icon(img: Image.Image, spec: dict, top: float) -> None:
    """The TV rating icon in the top-left corner, ``top`` pixels down (below a top-left ribbon),
    on a dark backing so the white icon reads on any poster."""
    w, _ = img.size
    icon = Image.open(TV_ICONS / f"{spec['tv_icon']}.png").convert("RGBA")
    height = int(w * 0.11 * BADGE_SIZES.get(spec.get("size") or "medium", 1.0))
    icon = icon.resize((round(icon.width * height / icon.height), height), Image.LANCZOS)
    margin = int(w * 0.04)
    x, y = margin, int(max(margin, top + margin * 0.5))
    pad = max(2, height // 14)
    backing = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(backing).rounded_rectangle([x - pad, y - pad, x + icon.width + pad, y + height + pad],
                                              radius=pad * 2, fill=(0, 0, 0, 130))
    img.alpha_composite(backing)
    img.alpha_composite(icon, (x, y))


def render(original: bytes, specs: list[dict]) -> bytes:
    """The original poster with ``specs`` drawn on it, as a JPEG."""
    try:
        img = Image.open(io.BytesIO(original)).convert("RGBA")
    except OSError as exc:
        raise OverlayError(f"Plex's poster isn't a readable image: {exc}") from exc
    if img.width != W:
        img = img.resize((W, round(img.height * W / img.width)), Image.LANCZOS)
    corners: dict[str, int] = {}
    clear: dict[str, float] = {}      # how far bottom-corner ribbons reach along the bottom edge
    top_left = 0.0                    # how far a top-left ribbon reaches down the left edge
    for spec in (s for s in specs if s["kind"] == "ribbon"):
        slot = corners.get(spec["corner"], 0)
        corners[spec["corner"]] = slot + 1
        reach = _ribbon(img, spec, slot)
        _, side, end = CORNERS.get(spec["corner"], CORNERS["top-right"])
        if end == "bottom":
            clear[side] = max(clear.get(side, 0), reach)
        elif side == "left":
            top_left = max(top_left, reach)
    for spec in (s for s in specs if s["kind"] == "badges"):
        if spec.get("tv_icon"):
            _tv_icon(img, spec, top_left)
        _badges(img, spec, clear)
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


def preview(specs: list[dict], plex: Plex | None = None, thumb: str = "", rating_key: str = "",
            fresh: bool = False) -> bytes:
    """``specs`` drawn on a title's poster (its fresh one with ``fresh``), or on a plain sample."""
    if plex and thumb:
        try:
            base = plex.image(thumb)[0]
            if fresh and rating_key:
                choice = plex.fresh_choice(rating_key)
                if choice:
                    base = plex.poster_bytes(choice)
            return render(base, specs)
        except (PlexError, OverlayError):
            pass                     # fall back to the plain sample
    return render(sample_poster(), specs)


# --- what goes where ---------------------------------------------------------------

def ribbon_spec(cfg: CollectionConfig) -> dict | None:
    if cfg.kind not in ("collection", "overlay") or not cfg.ribbon.enabled:
        return None
    spec = {"kind": "ribbon", **cfg.ribbon.model_dump(exclude={"enabled"})}
    if not spec["image"]:                 # only when used, so text ribbons keep their signature
        del spec["image"]
    elif _ribbon_image(spec["image"]) is not None:
        spec["corner"] = "bottom-right"   # pictures are made for that corner (badges move clear of it)
    return spec


def badge_settings(cfg: CollectionConfig) -> dict | None:
    if cfg.kind not in ("collection", "overlay") or not (cfg.badges.quality or cfg.badges.rating
                                                         or cfg.badges.content_rating or cfg.badges.tv_icon):
        return None
    return cfg.badges.model_dump()


def uses_overlays(cfg: CollectionConfig) -> bool:
    """Whether a collection changes its titles' posters at all (ribbon, badges or a fresh poster)."""
    return bool(ribbon_spec(cfg) or badge_settings(cfg)
                or (cfg.kind in ("collection", "overlay") and cfg.fresh_poster))


# --- whole-library badges ------------------------------------------------------------
# Stored in the "library_overlays" setting: {section id: Badges settings}.

def library_settings() -> dict[str, dict]:
    """Badge settings for whole libraries, keeping only libraries with something turned on."""
    from .models import Badges
    try:
        saved = json.loads(db.get_settings().get("library_overlays") or "{}")
    except ValueError:
        return {}
    out = {}
    for section_id, raw in (saved.items() if isinstance(saved, dict) else []):
        try:
            badges = Badges(**raw).model_dump()
        except (TypeError, ValueError):
            continue
        if badges["quality"] or badges["rating"] or badges["content_rating"] or badges["tv_icon"]:
            out[str(section_id)] = badges
    return out


def save_library_settings(settings: dict[str, dict]) -> dict[str, dict]:
    from .models import Badges
    clean = {str(k): Badges(**v).model_dump() for k, v in settings.items()}
    db.save_settings({"library_overlays": json.dumps(clean)})
    return library_settings()


def needed() -> bool:
    """Whether an overlay pass has anything to do (overlays wanted, or ones to remove)."""
    if db.overlay_rows() or library_settings():
        return True
    return any(uses_overlays(CollectionConfig(**r["config"])) for r in db.list_collections())


def _merge_badges(entry: dict, badges: dict) -> None:
    merged = entry["badges"] or {"quality": False, "content_rating": False, "rating": "", "rating_min": 0,
                                 "size": badges.get("size") or "medium"}
    order = list(BADGE_SIZES)                          # the largest size asked for wins
    if order.index(badges.get("size") or "medium") > order.index(merged.get("size") or "medium"):
        merged["size"] = badges["size"]
    merged["quality"] = merged["quality"] or badges["quality"]
    merged["content_rating"] = merged["content_rating"] or badges["content_rating"]
    merged["tv_icon"] = merged.get("tv_icon") or badges.get("tv_icon", False)
    if badges["rating"] and not merged["rating"]:      # the first choice wins
        merged["rating"], merged["rating_min"] = badges["rating"], badges["rating_min"]
    entry["badges"] = merged


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
        if not uses_overlays(cfg):
            continue
        if cfg.kind == "overlay":           # a list overlay: the titles its last sync found
            if not row.get("members"):
                continue
            items = plex.items_meta(row["members"])
        elif not row.get("plex_rating_key"):
            continue
        try:
            items = items if cfg.kind == "overlay" else plex.collection_raw(row["plex_rating_key"])
        except PlexError as exc:
            if exc.status != 404:
                raise
            continue
        for item in items:
            rk = str(item["ratingKey"])
            entry = wanted.setdefault(rk, {
                "ribbons": [], "badges": None, "fresh": False, "item": item, "section_id": cfg.section_id,
                "type": item.get("type") or "movie", "thumb": item.get("thumb") or ""})
            entry["fresh"] = entry["fresh"] or cfg.fresh_poster
            if ribbon:
                entry["ribbons"].append({**ribbon, "collection": row["id"]})
            if badges:
                _merge_badges(entry, badges)
    # Whole libraries: every movie or show in them gets the library's badges too.
    libraries = library_settings()
    if libraries:
        for section in plex.sections():
            badges = libraries.get(section["id"])
            if not badges:
                continue
            progress.update(phase=f"Checking {section['title']}")
            for item in plex.section_items(section["id"], section["type"]):
                rk = str(item["ratingKey"])
                entry = wanted.setdefault(rk, {
                    "ribbons": [], "badges": None, "fresh": False, "item": item, "section_id": section["id"],
                    "type": item.get("type") or section["type"], "thumb": item.get("thumb") or ""})
                _merge_badges(entry, badges)
    return wanted


def _specs(plex: Plex, rk: str, entry: dict, row: dict | None) -> tuple[list[dict], str, list]:
    """The overlays to draw on one title, plus its media key and quality labels to cache."""
    specs = [{"kind": "fresh"}] if entry.get("fresh") else []
    specs += sorted(entry["ribbons"], key=lambda s: s["collection"])
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
    certificate = ""
    if settings and settings.get("content_rating"):
        if not item.get("contentRating"):
            detail = detail or plex.item(rk) or item
        certificate = content_rating_label((item.get("contentRating") or (detail or {}).get("contentRating")))
    icon = ""
    if settings and settings.get("tv_icon") and entry["type"] == "show":
        if not item.get("contentRating"):
            detail = detail or plex.item(rk) or item
        icon = tv_icon_name(item.get("contentRating") or (detail or {}).get("contentRating"))
    if quality or rating or certificate or icon:
        badge = {"kind": "badges", "quality": quality, "rating": rating, "size": settings.get("size") or "medium"}
        if certificate:             # only when used, so posters drawn before 0.14 keep their signature
            badge["content_rating"] = certificate
        if icon:
            badge["tv_icon"] = icon
        specs.append(badge)
    return specs, key, quality


def content_rating_label(rating: str | None) -> str:
    """"PG-13", "TV-MA", or a country's rating without its prefix ("gb/12A" -> "12A")."""
    return (rating or "").split("/")[-1].strip()


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
    base = path.read_bytes()
    if entry.get("fresh") and not _keeps_poster(plex, rk):     # a clean poster from Plex's sources
        fresh = plex.fresh_choice(rk)
        if fresh:
            base = plex.poster_bytes(fresh)
    plex.upload_image(rk, "poster", data=render(base, specs))
    new_thumb = (plex.item(rk) or {}).get("thumb") or ""
    db.save_overlay(rk, entry["section_id"], entry["type"], sig, new_thumb, key, quality)
    if not row:
        try:
            plex.set_item_label(entry["section_id"], rk, entry["type"], LABEL, True)
        except PlexError as exc:
            log.debug("Could not label %s: %s", rk, exc)
    return True


def _keeps_poster(plex: Plex, rk: str) -> bool:
    """Titles labelled "Curatarr Keep Poster" keep their own poster under any overlays."""
    from .unmatched import has_keep_label
    return has_keep_label(plex.item(rk) or {})


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
    progress.update(running=True, phase="Checking collections", done=0, total=0, drawn=0, restored=0,
                    errors=0, started=db.now(), finished=None)
    try:
        _run_pass(remove_all, counts)
    finally:
        progress.update(running=False, phase="", finished=db.now())
    return counts


def _run_pass(remove_all: bool, counts: dict) -> None:
    with plexmod.from_settings(db.get_settings()) as plex:
        wanted = {} if remove_all else _wanted(plex)
        rows = db.overlay_rows()
        restore = [rk for rk in rows if rk not in wanted]
        progress.update(phase="Restoring original posters" if remove_all else "Drawing poster overlays",
                        total=len(wanted) + len(restore))
        for rk, entry in wanted.items():
            try:
                done = _apply_one(plex, rk, entry, rows.get(rk))
                counts["drawn" if done else "unchanged" if done is False else "nothing"] += 1
            except (PlexError, OverlayError, PosterError, OSError) as exc:
                counts["errors"] += 1
                log.warning("Overlay for %s failed: %s", rk, exc)
            progress.update(done=progress["done"] + 1, drawn=counts["drawn"], errors=counts["errors"])
        for rk in restore:
            try:
                _restore_one(plex, rk, rows[rk])
                counts["restored"] += 1
            except (PlexError, OSError) as exc:
                counts["errors"] += 1
                log.warning("Restoring the poster of %s failed: %s", rk, exc)
            progress.update(done=progress["done"] + 1, restored=counts["restored"], errors=counts["errors"])
    log.info("Overlays: %d title(s) with overlays: %d drawn, %d unchanged, %d with nothing to show "
             "(e.g. no rating); %d restored, %d failed", len(wanted), counts["drawn"], counts["unchanged"],
             counts["nothing"], counts["restored"], counts["errors"])
