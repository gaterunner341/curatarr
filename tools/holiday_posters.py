"""Render the built-in holiday collection posters (app/static/holidays/*.jpg).

The drawing code lives in app/posters.py. Run from the repo root:

    python tools/holiday_posters.py            # all of them
    python tools/holiday_posters.py football   # just some

The committed posters were drawn with Bodoni Bold and Bahnschrift (Windows);
other systems fall back to Georgia or DejaVu.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.posters import POSTERS, render  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "holidays"

if __name__ == "__main__":
    only = set(sys.argv[1:])
    OUT.mkdir(parents=True, exist_ok=True)
    for key, name, emblem, colors in POSTERS:
        if not only or key in only:
            path = OUT / f"{key}.jpg"
            render(name, emblem, colors).save(path, quality=90, optimize=True, progressive=True)
            print(path)
