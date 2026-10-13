#!/usr/bin/env python3
"""Draw the app icon and write it as PNG + multi-size ICO.

    python make_icon.py

Writes assets/icon.png (256px), assets/logo.png (512px, for the README) and
assets/icon.ico (16-256px, used by PyInstaller).  Everything is drawn at four
times the target size and downsampled with LANCZOS, which is what keeps the
curves smooth; Pillow is the only dependency, and only for this script -- the
app itself stays stdlib-only.
"""

import os
from PIL import Image, ImageDraw, ImageFilter

SS = 4                 # supersampling factor
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# Palette ---------------------------------------------------------------------
BG_TOP = (125, 211, 252)      # sky
BG_BOTTOM = (79, 123, 247)    # indigo
BOX = (255, 247, 232)         # cream carton
BOX_EDGE = (236, 214, 180)
LID = (255, 198, 116)         # warm amber lid
LID_EDGE = (240, 168, 78)
INK = (58, 58, 85)            # eyes / mouth
# ImageDraw replaces pixels instead of blending, so a translucent fill would
# show the tile behind it rather than the carton.  These are pre-blended
# against the cream body, which keeps every fill opaque.
BLUSH = (255, 198, 200)
GLINT = (205, 215, 245)
WHITE = (255, 255, 255)
ACCENT = (79, 123, 247)


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def canvas(size):
    """Rounded gradient tile with a transparent outside."""
    w = size * SS
    strip = Image.new("RGB", (1, w))
    px = strip.load()
    for y in range(w):
        px[0, y] = lerp(BG_TOP, BG_BOTTOM, y / (w - 1))
    bg = strip.resize((w, w), Image.BILINEAR)

    mask = Image.new("L", (w, w), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, w - 1, w - 1], radius=int(w * 0.225), fill=255
    )
    tile = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    tile.paste(bg, (0, 0), mask)
    return tile, w


def draw_icon(size):
    tile, w = canvas(size)
    layer = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    def r(*f):
        """Fractions of the canvas -> pixels."""
        return [v * w for v in f]

    # Soft drop shadow under the box, so it sits on the tile rather than in it.
    shadow = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        r(0.225, 0.46, 0.775, 0.83), radius=0.06 * w, fill=(30, 45, 110, 90)
    )
    tile.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(0.022 * w)))

    # Carton body.
    d.rounded_rectangle(r(0.245, 0.44, 0.755, 0.80), radius=0.055 * w,
                        fill=BOX, outline=BOX_EDGE, width=max(1, int(0.006 * w)))
    # Lid, drawn after the body so its lower edge overlaps the carton.
    d.rounded_rectangle(r(0.205, 0.345, 0.795, 0.462), radius=0.05 * w,
                        fill=LID, outline=LID_EDGE, width=max(1, int(0.006 * w)))
    # Handle notch in the lid.
    d.rounded_rectangle(r(0.455, 0.372, 0.545, 0.402), radius=0.015 * w,
                        fill=LID_EDGE)

    # Face.
    for cx in (0.385, 0.615):
        d.ellipse(r(cx - 0.048, 0.585 - 0.057, cx + 0.048, 0.585 + 0.057), fill=INK)
        d.ellipse(r(cx - 0.030, 0.585 - 0.042, cx - 0.004, 0.585 - 0.008), fill=WHITE)
        d.ellipse(r(cx + 0.006, 0.585 + 0.008, cx + 0.024, 0.585 + 0.030),
                  fill=GLINT)
    for cx in (0.312, 0.688):
        d.ellipse(r(cx - 0.052, 0.658 - 0.030, cx + 0.052, 0.658 + 0.030),
                  fill=BLUSH)
    # Smile: an arc, thick enough to survive the downsample.
    d.arc(r(0.435, 0.620, 0.565, 0.712), start=15, end=165,
          fill=INK, width=max(1, int(0.020 * w)))

    # Speech bubble, signalling "chat", tucked over the top-right corner.
    bub = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bub)
    bd.rounded_rectangle(r(0.600, 0.105, 0.905, 0.300), radius=0.062 * w,
                         fill=WHITE)
    bd.polygon([(0.660 * w, 0.292 * w), (0.640 * w, 0.392 * w),
                (0.742 * w, 0.296 * w)], fill=WHITE)
    for cx in (0.687, 0.752, 0.817):
        bd.ellipse(r(cx - 0.021, 0.2025 - 0.021, cx + 0.021, 0.2025 + 0.021),
                   fill=ACCENT)
    tile.alpha_composite(bub)
    tile.alpha_composite(layer)

    return tile.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(OUT, exist_ok=True)
    icon = draw_icon(256)
    icon.save(os.path.join(OUT, "icon.png"))
    draw_icon(512).save(os.path.join(OUT, "logo.png"))
    icon.save(os.path.join(OUT, "icon.ico"),
              sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    for name in ("icon.png", "logo.png", "icon.ico"):
        path = os.path.join(OUT, name)
        print(f"{os.path.getsize(path):>8}  assets/{name}")


if __name__ == "__main__":
    main()
