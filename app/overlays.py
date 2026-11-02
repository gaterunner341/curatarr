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


def needed() -> bool:
    """Whether an overlay pass has anything to do (overlays wanted, or ones to remove)."""
    return bool(db.overlay_rows()) or any(
        ribbon_spec(CollectionConfig(**r["config"])) for r in db.list_collections())


def _wanted(plex: Plex) -> dict[str, dict]:
    """rating key -> {specs, section_id, type, thumb} for every title that should carry overlays."""
    wanted: dict[str, dict] = {}
    for row in db.list_collections():
        cfg = CollectionConfig(**row["config"])
        spec = ribbon_spec(cfg)
        if not spec or not row.get("plex_rating_key"):
            continue
        try:
            items = plex.collection_contents(row["plex_rating_key"])
        except PlexError as exc:
            if exc.status != 404:
                raise
            continue
        for item in items:
            entry = wanted.setdefault(item["ratingKey"], {
                "specs": [], "section_id": cfg.section_id, "type": item.get("type") or "movie",
                "thumb": item.get("thumb") or ""})
            entry["specs"].append({**spec, "collection": row["id"]})
    return wanted


def signature(specs: list[dict]) -> str:
    return hashlib.sha1(json.dumps([STYLE_VERSION, specs], sort_keys=True).encode()).hexdigest()


# --- applying ------------------------------------------------------------------------

def _original_path(rating_key: str):
    return ORIGINALS / f"{rating_key}.jpg"


def _apply_one(plex: Plex, rk: str, entry: dict, row: dict | None) -> bool:
    """Draw a title's overlays if they changed. Returns True when its poster was uploaded."""
    specs = sorted(entry["specs"], key=lambda s: s["collection"])
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
    db.save_overlay(rk, entry["section_id"], entry["type"], sig, new_thumb)
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
    counts = {"drawn": 0, "restored": 0, "unchanged": 0, "errors": 0}
    with plexmod.from_settings(db.get_settings()) as plex:
        wanted = {} if remove_all else _wanted(plex)
        rows = db.overlay_rows()
        for rk, entry in wanted.items():
            try:
                if _apply_one(plex, rk, entry, rows.get(rk)):
                    counts["drawn"] += 1
                else:
                    counts["unchanged"] += 1
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
    if counts["drawn"] or counts["restored"] or counts["errors"]:
        log.info("Overlays: %d drawn, %d restored, %d unchanged, %d failed", counts["drawn"],
                 counts["restored"], counts["unchanged"], counts["errors"])
    return counts
