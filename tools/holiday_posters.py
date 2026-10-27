"""Render the built-in holiday collection posters (app/static/holidays/*.jpg).

One consistent series: dark vertical gradient, soft glow behind a single
emblem, serif title, letter-spaced "COLLECTION" and a thin inset frame.
Run from the repo root after `pip install pillow`:

    python tools/holiday_posters.py

Fonts are looked up in the usual Windows/Linux font folders; the rendered
JPEGs are committed, so the app itself never needs Pillow or the fonts.
"""
import math
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

W, H = 1000, 1500
S = 2                                     # supersampling factor for smooth edges
OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "holidays"

FONT_DIRS = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts"), Path("/Library/Fonts")]
TITLE_FONTS = ["BOD_B.TTF", "georgiab.ttf", "DejaVuSerif-Bold.ttf"]
LABEL_FONTS = ["bahnschrift.ttf", "segoeui.ttf", "DejaVuSans.ttf"]


def font(names: list[str], size: int) -> ImageFont.FreeTypeFont:
    for directory in FONT_DIRS:
        for name in names:
            for path in [directory / name, *directory.rglob(name)] if directory.exists() else []:
                if path.is_file():
                    return ImageFont.truetype(str(path), size)
    sys.exit(f"None of these fonts were found: {names}")


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


def render(key, name, emblem, colors):
    size = (W * S, H * S)
    img = gradient(colors["top"], colors["bottom"], size)

    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    gx, gy, gr = size[0] / 2, size[1] * 0.38, size[0] * 0.42
    ImageDraw.Draw(glow).ellipse([gx - gr, gy - gr, gx + gr, gy + gr], fill=hex_rgb(colors["accent"], 70))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(160 * S)))

    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    s = size[0] * 0.56
    if emblem is emblem_easter:
        emblem(draw, gx, gy, s, colors, layer)
    else:
        emblem(draw, gx, gy, s, colors)
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

    out = img.resize((W, H), Image.LANCZOS).convert("RGB")
    OUT.mkdir(parents=True, exist_ok=True)
    out.save(OUT / f"{key}.jpg", quality=90, optimize=True, progressive=True)
    return OUT / f"{key}.jpg"


if __name__ == "__main__":
    only = set(sys.argv[1:])
    for key, name, emblem, colors in POSTERS:
        if not only or key in only:
            print(render(key, name, emblem, colors))
