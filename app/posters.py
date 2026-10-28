"""Holiday collection posters, all in one style.

Dark vertical gradient, soft glow behind a single emblem, serif title,
letter-spaced "COLLECTION" and a thin inset frame. The built-in holidays'
posters are rendered once with ``tools/holiday_posters.py`` and committed;
holidays you add yourself get theirs drawn by the app when you create them.
"""
import io
import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

W, H = 1000, 1500

FONT_DIRS = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts"), Path("/Library/Fonts")]
# Bodoni and Bahnschrift where they exist (how the built-in posters were made);
# the Docker image has the free DejaVu fonts.
TITLE_FONTS = ["BOD_B.TTF", "georgiab.ttf", "DejaVuSerif-Bold.ttf"]
LABEL_FONTS = ["bahnschrift.ttf", "segoeui.ttf", "DejaVuSans.ttf"]


class PosterError(Exception):
    pass


@lru_cache(maxsize=None)
def _font_path(names: tuple[str, ...]) -> str:
    for directory in FONT_DIRS:
        if not directory.exists():
            continue
        for name in names:
            for path in [directory / name, *directory.rglob(name)]:
                if path.is_file():
                    return str(path)
    raise PosterError(f"None of these fonts were found: {', '.join(names)}")


def font(names: list[str], size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_font_path(tuple(names)), size)


def hex_rgb(value: str, alpha: int = 255) -> tuple[int, int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha)


# --- shapes (all coordinates already in supersampled pixels) ---------------------------

def rotate(points, cx, cy, degrees):
    a = math.radians(degrees)
    return [(cx + (x - cx) * math.cos(a) - (y - cy) * math.sin(a),
             cy + (x - cx) * math.sin(a) + (y - cy) * math.cos(a)) for x, y in points]


def heart_points(cx, cy, size, n=240):
    """Classic heart curve; ``size`` is the full width."""
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        pts.append((cx + x * size / 34, cy + y * size / 34))
    return pts


def star_points(cx, cy, outer, inner, points=5, start=-90):
    pts = []
    for i in range(points * 2):
        r = outer if i % 2 == 0 else inner
        a = math.radians(start + i * 180 / points)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def egg_points(cx, cy, rx, ry, n=240):
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        widen = 1 + 0.14 * math.sin(t)          # narrower at the top, fuller at the bottom
        pts.append((cx + rx * math.cos(t) * widen, cy + ry * math.sin(t)))
    return pts


def leaf_points(cx, cy, length, width, angle, n=120):
    """A pointed lens-shaped leaf whose stem end sits at (cx, cy)."""
    pts = []
    for i in range(n + 1):
        t = i / n
        pts.append((cx + length * t, cy - width * math.sin(math.pi * t) ** 0.9))
    for i in range(n, -1, -1):
        t = i / n
        pts.append((cx + length * t, cy + width * math.sin(math.pi * t) ** 0.9))
    return rotate(pts, cx, cy, angle)


# --- emblems ---------------------------------------------------------------------------

def emblem_valentines(d, cx, cy, s, c):
    d.polygon(heart_points(cx + s * 0.16, cy + s * 0.06, s * 0.56), fill=hex_rgb(c["second"]))
    d.polygon(heart_points(cx - s * 0.08, cy - s * 0.04, s * 0.78), fill=hex_rgb(c["icon"]))


def emblem_st_patricks(d, cx, cy, s, c):
    leaf = s * 0.42
    for angle in (0, 120, 240):
        pts = heart_points(cx, cy - leaf * 0.47, leaf)
        d.polygon(rotate(pts, cx, cy, angle), fill=hex_rgb(c["icon"]))
    stem = [(cx - s * 0.025, cy), (cx + s * 0.025, cy),
            (cx + s * 0.16, cy + s * 0.52), (cx + s * 0.10, cy + s * 0.53)]
    d.polygon(stem, fill=hex_rgb(c["icon"]))
    d.ellipse([cx - s * 0.05, cy - s * 0.05, cx + s * 0.05, cy + s * 0.05], fill=hex_rgb(c["second"]))


def emblem_easter(d, cx, cy, s, c, layer):
    rx, ry = s * 0.30, s * 0.42
    egg = egg_points(cx, cy, rx, ry)
    d.polygon(egg, fill=hex_rgb(c["icon"]))
    bands = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(bands)
    for y_off, color, amp in ((-0.12, c["second"], 0.035), (0.10, c["third"], 0.035)):
        y = cy + s * y_off
        zig = []
        steps = 9
        for i in range(steps + 1):
            x = cx - rx * 1.3 + i * (rx * 2.6 / steps)
            zig.append((x, y + (amp * s if i % 2 else -amp * s)))
        band = zig + [(x, y + s * 0.08) for x, _ in reversed(zig)]
        bd.polygon(band, fill=hex_rgb(color))
    for i in range(5):
        x = cx - rx * 0.6 + i * rx * 0.3
        bd.ellipse([x - s * 0.018, cy + s * 0.27 - s * 0.018, x + s * 0.018, cy + s * 0.27 + s * 0.018],
                   fill=hex_rgb(c["second"]))
    mask = Image.new("L", layer.size, 0)
    ImageDraw.Draw(mask).polygon(egg, fill=255)
    layer.alpha_composite(Image.composite(bands, Image.new("RGBA", layer.size, (0, 0, 0, 0)), mask))


def burst(d, cx, cy, radius, rays, color, width):
    for i in range(rays):
        a = 2 * math.pi * i / rays
        x0, y0 = cx + radius * 0.28 * math.cos(a), cy + radius * 0.28 * math.sin(a)
        x1, y1 = cx + radius * math.cos(a), cy + radius * math.sin(a)
        d.line([(x0, y0), (x1, y1)], fill=color, width=width)
        r = width * 0.9
        d.ellipse([x1 - r, y1 - r, x1 + r, y1 + r], fill=color)


def emblem_independence(d, cx, cy, s, c):
    burst(d, cx - s * 0.30, cy - s * 0.30, s * 0.17, 14, hex_rgb(c["second"]), int(s * 0.012))
    burst(d, cx + s * 0.33, cy - s * 0.22, s * 0.13, 12, hex_rgb(c["third"]), int(s * 0.010))
    burst(d, cx + s * 0.28, cy + s * 0.33, s * 0.10, 10, hex_rgb(c["second"]), int(s * 0.009))
    d.polygon(star_points(cx, cy + s * 0.02, s * 0.36, s * 0.145), fill=hex_rgb(c["icon"]))


def emblem_halloween(d, cx, cy, s, c):
    body, rib = hex_rgb(c["icon"]), hex_rgb(c["second"])
    w, h = s * 0.80, s * 0.58
    top = cy - h / 2 + s * 0.05
    for frac, shade in ((0.62, rib), (0.40, hex_rgb(c["mid"]))):   # darker toward the sides
        for side in (-1, 1):
            x = cx + side * w * (0.5 - frac / 2)
            d.ellipse([x - w * frac / 2, top, x + w * frac / 2, top + h], fill=shade)
    d.ellipse([cx - w * 0.22, top - s * 0.01, cx + w * 0.22, top + h + s * 0.01], fill=body,
              outline=rib, width=int(s * 0.008))
    stem =[(cx - s * 0.035, top + s * 0.03), (cx + s * 0.035, top + s * 0.03),
            (cx + s * 0.06, top - s * 0.11), (cx + s * 0.0, top - s * 0.12)]
    d.polygon(stem, fill=hex_rgb(c["third"]))
    d.arc([cx + s * 0.02, top - s * 0.17, cx + s * 0.20, top - s * 0.02], 200, 330,
          fill=hex_rgb(c["third"]), width=int(s * 0.012))


def emblem_veterans(d, cx, cy, s, c):
    gold = hex_rgb(c["icon"])
    for r, wdt in ((0.44, 0.016), (0.39, 0.006)):
        d.ellipse([cx - s * r, cy - s * r, cx + s * r, cy + s * r], outline=gold, width=int(s * wdt))
    d.polygon(star_points(cx, cy + s * 0.015, s * 0.30, s * 0.12), fill=gold)
    for i, y in enumerate((0.52, 0.60)):       # chevrons below
        y0 = cy + s * y
        pts = [(cx - s * 0.16, y0 - s * 0.05), (cx, y0 + s * 0.03), (cx + s * 0.16, y0 - s * 0.05),
               (cx + s * 0.16, y0 - s * 0.005), (cx, y0 + s * 0.075), (cx - s * 0.16, y0 - s * 0.005)]
        d.polygon(pts, fill=hex_rgb(c["second"] if i else c["icon"]))


def emblem_thanksgiving(d, cx, cy, s, c):
    base = (cx, cy + s * 0.34)
    for angle, color, length in ((-125, c["third"], 0.62), (-55, c["second"], 0.62), (-90, c["icon"], 0.72)):
        pts = leaf_points(*base, s * length, s * 0.17, angle)
        d.polygon(pts, fill=hex_rgb(color))
        a = math.radians(angle)
        tip = (base[0] + s * length * 0.92 * math.cos(a), base[1] + s * length * 0.92 * math.sin(a))
        d.line([base, tip], fill=hex_rgb(c["vein"], 170), width=int(s * 0.008))
        for t in (0.35, 0.55, 0.75):
            px, py = base[0] + s * length * t * math.cos(a), base[1] + s * length * t * math.sin(a)
            for side in (-1, 1):
                b = a + side * math.radians(38)
                ln = s * 0.09 * (1 - t * 0.5)
                d.line([(px, py), (px + ln * math.cos(b), py + ln * math.sin(b))],
                       fill=hex_rgb(c["vein"], 140), width=int(s * 0.005))
    d.line([base, (base[0] + s * 0.03, base[1] + s * 0.12)], fill=hex_rgb(c["vein"]), width=int(s * 0.014))


def emblem_christmas(d, cx, cy, s, c):
    green, gold = hex_rgb(c["icon"]), hex_rgb(c["second"])
    tiers = [(-0.30, 0.18), (-0.13, 0.27), (0.06, 0.36), (0.26, 0.45)]
    for i, (y, half) in enumerate(tiers):
        top_y = cy + s * (y - 0.20)
        base_y = cy + s * (y + 0.04)
        d.polygon([(cx, top_y), (cx + s * half, base_y), (cx - s * half, base_y)], fill=green)
    d.rectangle([cx - s * 0.045, cy + s * 0.30, cx + s * 0.045, cy + s * 0.40], fill=hex_rgb(c["third"]))
    d.polygon(star_points(cx, cy - s * 0.52, s * 0.09, s * 0.037), fill=gold)
    # Ornaments at fixed spots: (tier index, horizontal position as a fraction of the tier half-width)
    ornaments = [(1, -0.45), (1, 0.40), (2, -0.15), (2, 0.55), (3, -0.60), (3, 0.05), (3, 0.62)]
    r = s * 0.022
    for tier, fx in ornaments:
        y, half = tiers[tier]
        x = cx + fx * s * half * 0.75
        yy = cy + s * (y - 0.005) + abs(fx) * s * 0.03
        d.ellipse([x - r, yy - r, x + r, yy + r], fill=gold)


POSTERS = [
    ("valentines", "Valentine’s Day", emblem_valentines,
     {"top": "#4a0d22", "bottom": "#0e0306", "icon": "#d8304e", "second": "#f2a7b6", "accent": "#f2b8c3"}),
    ("st-patricks", "St. Patrick’s Day", emblem_st_patricks,
     {"top": "#0d4128", "bottom": "#03100a", "icon": "#33a35c", "second": "#d9c27a", "accent": "#d9c27a"}),
    ("easter", "Easter", emblem_easter,
     {"top": "#3a3266", "bottom": "#0c0a18", "icon": "#f6e4ee", "second": "#8fcfc0", "third": "#f2c66d",
      "accent": "#e8d7f5"}),
    ("independence-day", "Independence Day", emblem_independence,
     {"top": "#12244f", "bottom": "#04070f", "icon": "#f4efe2", "second": "#d23a43", "third": "#f4efe2",
      "accent": "#e8696e"}),
    ("halloween", "Halloween", emblem_halloween,
     {"top": "#33160a", "bottom": "#070302", "icon": "#ea7a1f", "second": "#b9520f", "third": "#5b7a2c",
      "mid": "#d6691a",
      "accent": "#f0a43a"}),
    ("veterans-day", "Veteran’s Day", emblem_veterans,
     {"top": "#28331f", "bottom": "#070906", "icon": "#d8c27a", "second": "#9c8a4e", "accent": "#d8c27a"}),
    ("thanksgiving", "Thanksgiving", emblem_thanksgiving,
     {"top": "#45210d", "bottom": "#0d0602", "icon": "#d4651f", "second": "#e3a02f", "third": "#a3301f",
      "vein": "#5a2a10", "accent": "#e9b75a"}),
    ("christmas", "Christmas", emblem_christmas,
     {"top": "#0c3322", "bottom": "#030a06", "icon": "#23804e", "second": "#e8c25a", "third": "#6b3f1d",
      "accent": "#e8c25a"}),
]


def gradient(top, bottom, size):
    w, h = size
    t, b = hex_rgb(top), hex_rgb(bottom)
    column = Image.new("RGBA", (1, h))
    for y in range(h):
        f = (y / (h - 1)) ** 0.85
        column.putpixel((0, y), tuple(int(t[i] + (b[i] - t[i]) * f) for i in range(3)) + (255,))
    return column.resize((w, h))


def title_lines(text, fnt, max_width, draw):
    if draw.textlength(text, font=fnt) <= max_width or " " not in text:
        return [text]
    words = text.split()
    best = None
    for i in range(1, len(words)):         # most balanced two-line split
        a, b = " ".join(words[:i]), " ".join(words[i:])
        score = max(draw.textlength(a, font=fnt), draw.textlength(b, font=fnt))
        if best is None or score < best[0]:
            best = (score, [a, b])
    return best[1]


def spaced(draw, xy_center, text, fnt, fill, tracking):
    widths = [draw.textlength(ch, font=fnt) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = xy_center[0] - total / 2
    for ch, w in zip(text, widths):
        draw.text((x, xy_center[1]), ch, font=fnt, fill=fill, anchor="lm")
        x += w + tracking


def render(name, emblem, colors, S=2, **emblem_args):
    """The poster as an RGB image (W x H), drawn at ``S`` times the size for smooth edges."""
    size = (W * S, H * S)
    img = gradient(colors["top"], colors["bottom"], size)

    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    gx, gy, gr = size[0] / 2, size[1] * 0.38, size[0] * 0.42
    ImageDraw.Draw(glow).ellipse([gx - gr, gy - gr, gx + gr, gy + gr], fill=hex_rgb(colors["accent"], 70))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(160 * S)))

    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    s = size[0] * 0.56
    if emblem in NEEDS_LAYER:
        emblem(draw, gx, gy, s, colors, layer, **emblem_args)
    else:
        emblem(draw, gx, gy, s, colors, **emblem_args)
    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    shadow.putalpha(layer.getchannel("A").point(lambda a: int(a * 0.55)))
    img.alpha_composite(ImageChops.offset(shadow, 0, 14 * S).filter(ImageFilter.GaussianBlur(18 * S)))
    img.alpha_composite(layer)

    text = ImageDraw.Draw(img)
    inset = 38 * S
    text.rectangle([inset, inset, size[0] - inset, size[1] - inset],
                   outline=hex_rgb(colors["accent"], 110), width=2 * S)

    title_size = 118 * S
    while True:
        fnt = font(TITLE_FONTS, title_size)
        lines = title_lines(name.upper(), fnt, size[0] * 0.80, text)
        if all(text.textlength(line, font=fnt) <= size[0] * 0.80 for line in lines):
            break
        title_size -= 4 * S
    line_h = title_size * 1.08
    y = size[1] * (0.765 if len(lines) == 1 else 0.735)
    for line in lines:
        text.text((size[0] / 2, y), line, font=fnt, fill=hex_rgb("#f6f1e7"), anchor="mm")
        y += line_h
    rule_y = y - line_h / 2 + 46 * S
    text.line([(size[0] / 2 - 70 * S, rule_y), (size[0] / 2 + 70 * S, rule_y)],
              fill=hex_rgb(colors["accent"]), width=2 * S)
    spaced(text, (size[0] / 2, rule_y + 46 * S), "COLLECTION", font(LABEL_FONTS, 34 * S),
           hex_rgb(colors["accent"]), 14 * S)

    noise = Image.effect_noise(size, 18).convert("RGBA")
    noise.putalpha(14)
    img.alpha_composite(noise)

    return img.resize((W, H), Image.LANCZOS).convert("RGB")




# --- emblems for the holidays added in 0.11.0 ------------------------------------------

def emblem_new_years(d, cx, cy, s, c):
    burst(d, cx - s * 0.36, cy - s * 0.34, s * 0.14, 12, hex_rgb(c["second"]), int(s * 0.010))
    burst(d, cx + s * 0.38, cy - s * 0.30, s * 0.11, 10, hex_rgb(c["icon"]), int(s * 0.009))
    gold = hex_rgb(c["icon"])
    r = s * 0.32
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=gold, width=int(s * 0.022))
    for i in range(12):
        a = math.radians(i * 30 - 90)
        inner = r * (0.78 if i % 3 == 0 else 0.86)
        d.line([(cx + inner * math.cos(a), cy + inner * math.sin(a)),
                (cx + r * 0.93 * math.cos(a), cy + r * 0.93 * math.sin(a))],
               fill=gold, width=int(s * (0.016 if i % 3 == 0 else 0.008)))
    d.line([(cx, cy), (cx - r * 0.06, cy - r * 0.52)], fill=hex_rgb(c["second"]), width=int(s * 0.022))
    d.line([(cx, cy), (cx, cy - r * 0.72)], fill=hex_rgb(c["second"]), width=int(s * 0.014))
    d.ellipse([cx - s * 0.03, cy - s * 0.03, cx + s * 0.03, cy + s * 0.03], fill=gold)


def emblem_mothers_day(d, cx, cy, s, c):
    stem = hex_rgb(c["third"])
    d.line([(cx, cy), (cx + s * 0.04, cy + s * 0.56)], fill=stem, width=int(s * 0.022))
    d.polygon(leaf_points(cx + s * 0.02, cy + s * 0.36, s * 0.26, s * 0.075, -30), fill=stem)
    d.polygon(leaf_points(cx + s * 0.03, cy + s * 0.46, s * 0.22, s * 0.065, 200), fill=stem)
    petal = hex_rgb(c["icon"])
    outline = [(s * 0.17 * math.cos(math.radians(t)) + s * 0.17, s * 0.10 * math.sin(math.radians(t)))
               for t in range(0, 360, 6)]
    for i in range(6):
        d.polygon(rotate([(cx + x, cy + y) for x, y in outline], cx, cy, i * 60), fill=petal)
    d.ellipse([cx - s * 0.075, cy - s * 0.075, cx + s * 0.075, cy + s * 0.075], fill=hex_rgb(c["second"]))


def emblem_fathers_day(d, cx, cy, s, c, layer):
    tie = hex_rgb(c["icon"])
    knot = [(cx - s * 0.10, cy - s * 0.44), (cx + s * 0.10, cy - s * 0.44),
            (cx + s * 0.065, cy - s * 0.30), (cx - s * 0.065, cy - s * 0.30)]
    blade = [(cx - s * 0.06, cy - s * 0.29), (cx + s * 0.06, cy - s * 0.29), (cx + s * 0.19, cy + s * 0.36),
             (cx, cy + s * 0.52), (cx - s * 0.19, cy + s * 0.36)]
    d.polygon(knot, fill=tie)
    d.polygon(blade, fill=tie)
    stripes = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(stripes)
    for i in range(-6, 9):
        y = cy - s * 0.25 + i * s * 0.11
        sd.line([(cx - s * 0.3, y + s * 0.18), (cx + s * 0.3, y - s * 0.18)],
                fill=hex_rgb(c["second"], 150), width=int(s * 0.024))
    mask = Image.new("L", layer.size, 0)
    ImageDraw.Draw(mask).polygon(blade, fill=255)
    layer.alpha_composite(Image.composite(stripes, Image.new("RGBA", layer.size, (0, 0, 0, 0)), mask))


def flame(d, x, y, h, color):
    """A candle flame whose base sits at (x, y), ``h`` tall."""
    pts = []
    for i in range(60):
        t = 2 * math.pi * i / 60
        pts.append((x + h * 0.45 * math.sin(t) * (1 - math.cos(t)) / 2, y - h * (1 - math.cos(t)) / 2))
    d.polygon(pts, fill=color)


def emblem_hanukkah(d, cx, cy, s, c):
    silver, gold = hex_rgb(c["icon"]), hex_rgb(c["second"])
    w = int(s * 0.020)
    arm_y = cy - s * 0.18
    base_y = cy + s * 0.40
    d.rectangle([cx - s * 0.17, base_y, cx + s * 0.17, base_y + s * 0.04], fill=silver)
    d.line([(cx, base_y), (cx, arm_y - s * 0.10)], fill=silver, width=int(s * 0.03))
    for k in range(1, 5):                          # four arms each side, as half rings
        r = s * 0.095 * k
        d.arc([cx - r, arm_y - r, cx + r, arm_y + r], 0, 180, fill=silver, width=w)
    for i in range(9):
        x = cx + s * 0.095 * (i - 4)
        top = arm_y - (s * 0.10 if i == 4 else 0)        # the shamash stands higher
        d.rectangle([x - s * 0.018, top - s * 0.09, x + s * 0.018, top], fill=hex_rgb(c["third"]))
        flame(d, x, top - s * 0.095, s * 0.075, gold)


def emblem_lunar_new_year(d, cx, cy, s, c):
    red, gold, rib = hex_rgb(c["icon"]), hex_rgb(c["second"]), hex_rgb(c["mid"])
    rx, ry = s * 0.34, s * 0.27
    d.line([(cx, cy - ry - s * 0.20), (cx, cy - ry)], fill=gold, width=int(s * 0.012))
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=red)
    for k in (0.35, 0.7):
        d.ellipse([cx - rx * k, cy - ry, cx + rx * k, cy + ry], outline=rib, width=int(s * 0.010))
    d.line([(cx, cy - ry), (cx, cy + ry)], fill=rib, width=int(s * 0.010))
    for y in (cy - ry, cy + ry):
        d.rounded_rectangle([cx - s * 0.13, y - s * 0.035, cx + s * 0.13, y + s * 0.035],
                            radius=int(s * 0.012), fill=gold)
    for i in range(7):
        x = cx - s * 0.06 + i * s * 0.02
        d.line([(x, cy + ry + s * 0.04), (x + (i - 3) * s * 0.004, cy + ry + s * 0.24)],
               fill=gold, width=int(s * 0.007))
    d.ellipse([cx - s * 0.03, cy + ry + s * 0.025, cx + s * 0.03, cy + ry + s * 0.075], fill=gold)


def emblem_back_to_school(d, cx, cy, s, c):
    red = hex_rgb(c["icon"])
    d.ellipse([cx - s * 0.30, cy - s * 0.20, cx + s * 0.04, cy + s * 0.32], fill=red)
    d.ellipse([cx - s * 0.04, cy - s * 0.20, cx + s * 0.30, cy + s * 0.32], fill=red)
    d.ellipse([cx - s * 0.20, cy - s * 0.10, cx + s * 0.20, cy + s * 0.38], fill=red)
    d.ellipse([cx - s * 0.20, cy - s * 0.12, cx - s * 0.08, cy + s * 0.02], fill=hex_rgb(c["mid"]))
    d.line([(cx, cy - s * 0.16), (cx + s * 0.03, cy - s * 0.34)], fill=hex_rgb(c["third"]), width=int(s * 0.024))
    d.polygon(leaf_points(cx + s * 0.03, cy - s * 0.27, s * 0.22, s * 0.07, -25), fill=hex_rgb(c["second"]))


def emblem_football(d, cx, cy, s, c):
    angle = -28
    d.polygon(rotate(leaf_points(cx - s * 0.40, cy, s * 0.80, s * 0.27, 0), cx, cy, angle),
              fill=hex_rgb(c["icon"]))
    white = hex_rgb(c["second"])

    def bar(x0, x1, y0, y1):
        d.polygon(rotate([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], cx, cy, angle), fill=white)
    for side in (-1, 1):
        x = cx + side * s * 0.25
        bar(x - s * 0.018, x + s * 0.018, cy - s * 0.17, cy + s * 0.17)
    bar(cx - s * 0.12, cx + s * 0.12, cy - s * 0.008, cy + s * 0.008)
    for i in range(-3, 4):
        x = cx + i * s * 0.035
        bar(x - s * 0.007, x + s * 0.007, cy - s * 0.045, cy + s * 0.045)


def emblem_monogram(d, cx, cy, s, c, layer, letter="★"):
    """For holidays you add yourself: a ringed initial."""
    ring = hex_rgb(c["icon"])
    for r, w in ((0.40, 0.016), (0.35, 0.006)):
        d.ellipse([cx - s * r, cy - s * r, cx + s * r, cy + s * r], outline=ring, width=int(s * w))
    d.polygon(star_points(cx, cy - s * 0.40, s * 0.05, s * 0.02), fill=hex_rgb(c["second"]))
    d.text((cx, cy + s * 0.02), letter, font=font(TITLE_FONTS, int(s * 0.44)), fill=hex_rgb(c["second"]),
           anchor="mm")


NEEDS_LAYER = {emblem_easter, emblem_fathers_day, emblem_monogram}

POSTERS += [
    ("new-years", "New Year’s", emblem_new_years,
     {"top": "#1b1640", "bottom": "#05040d", "icon": "#e8c25a", "second": "#c9c2f0", "accent": "#e8c25a"}),
    ("mothers-day", "Mother’s Day", emblem_mothers_day,
     {"top": "#4a1638", "bottom": "#10040c", "icon": "#f08fb8", "second": "#ffd36e", "third": "#4f9a5a",
      "accent": "#f5b3cf"}),
    ("fathers-day", "Father’s Day", emblem_fathers_day,
     {"top": "#14304a", "bottom": "#040a10", "icon": "#3f78b5", "second": "#c9d6e3", "accent": "#9cc0e0"}),
    ("hanukkah", "Hanukkah", emblem_hanukkah,
     {"top": "#0f2350", "bottom": "#03071a", "icon": "#c9d3f2", "second": "#f2c14e", "third": "#eef2ff",
      "accent": "#9fb7ef"}),
    ("lunar-new-year", "Lunar New Year", emblem_lunar_new_year,
     {"top": "#4a0a0a", "bottom": "#0f0202", "icon": "#d8322b", "second": "#e8c25a", "mid": "#a8221d",
      "accent": "#f0c45a"}),
    ("back-to-school", "Back to School", emblem_back_to_school,
     {"top": "#3a2410", "bottom": "#0b0703", "icon": "#c8332c", "second": "#5a9a3a", "third": "#5a3a1d",
      "mid": "#e2645b", "accent": "#e9b75a"}),
    ("football", "Football", emblem_football,
     {"top": "#13361f", "bottom": "#030b06", "icon": "#8a4b25", "second": "#f4efe2", "accent": "#d9e6c8"}),
]

# Colour schemes for holidays you add yourself.
SCHEMES = {
    "crimson": {"top": "#4a0d1a", "bottom": "#0e0305", "icon": "#d8304e", "second": "#f2b8c3", "accent": "#f2b8c3"},
    "emerald": {"top": "#0d4128", "bottom": "#03100a", "icon": "#33a35c", "second": "#d9c27a", "accent": "#d9c27a"},
    "royal": {"top": "#12244f", "bottom": "#04070f", "icon": "#6f8fe0", "second": "#f4efe2", "accent": "#9fb4ef"},
    "amber": {"top": "#45210d", "bottom": "#0d0602", "icon": "#e3a02f", "second": "#f6e3b4", "accent": "#e9b75a"},
    "plum": {"top": "#3a1a4d", "bottom": "#0c0512", "icon": "#b07ad6", "second": "#f0d1ff", "accent": "#d9b3f0"},
    "slate": {"top": "#26303b", "bottom": "#07090c", "icon": "#c9d3dd", "second": "#e8edf2", "accent": "#c9d3dd"},
    "gold": {"top": "#2b2410", "bottom": "#080703", "icon": "#e8c25a", "second": "#f6e9c0", "accent": "#e8c25a"},
}


def custom_poster(name: str, scheme: str) -> bytes:
    """A JPEG poster for a holiday you added, in the same style as the built-in ones."""
    letter = next((ch for ch in name if ch.isalnum()), "★").upper()
    # S=1 keeps it quick on a NAS; the built-in posters are drawn at S=2.
    image = render(name, emblem_monogram, SCHEMES.get(scheme) or SCHEMES["royal"], S=1, letter=letter)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=90, optimize=True, progressive=True)
    return out.getvalue()
