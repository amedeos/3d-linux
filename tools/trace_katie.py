"""Trace Katie, the KDE mascot, from Tyson Tan's picture into an SVG with flat colours.

Katie exists only as a raster picture (her 2026 redesign for KDE's 30th birthday). This
script makes src/linux3d/assets/kde/katie.svg from it, the same way every time:

1. Download the PNG and check its SHA-256.
2. Snap every pixel to the drawing's own palette (PALETTE): the soft edges between two
   colours must not become slivers of a third colour.
3. Scale it down to about 2000 px tall (0.06 mm a pixel at 120 mm), by majority vote.
4. Keep only the figure: the sparkles beside her are separate pieces.
5. Trace the colour areas with vtracer, stacked: each colour is painted over the ones
   below it, as in the drawing.
6. vtracer averages the colours of each area, so a fill can be off by one step: set every
   fill back to its palette colour, so figures.py can name the colours exactly.

Run it from the repository root, in its own environment: vtracer's wheel for Python 3.14
crashes (segmentation fault), the one for 3.13 works:

    uv run --no-project --python 3.13 --with vtracer==0.6.15 --with pillow \
        --with numpy --with scipy python tools/trace_katie.py
"""

import hashlib
import io
import re
import sys
import urllib.request
from pathlib import Path

import numpy as np
import vtracer
from PIL import Image
from scipy import ndimage

URL = "https://community.kde.org/images.community/3/31/Mascot-katie-kde30logo-katie.png"
SHA256 = "9dc84bc818c726599153fbb654243afb726d92fa1f5190002f90a804136a9888"
OUT = Path(__file__).resolve().parents[1] / "src/linux3d/assets/kde/katie.svg"
HEIGHT = 2000  # px, about: the picture is scaled down by a whole factor

# The flat colours of the drawing: together they cover 98 % of the figure, and the rest
# are soft edges between two of them (measured on the PNG).
PALETTE = [
    "#bbeb8c",  # skin: head, arms
    "#f1eee7",  # hoodie, shorts, leggings
    "#6ddd6d",  # hands, tail, feet
    "#ffd465",  # antlers, hoodie front
    "#ffaf2f",  # tail spikes, shading on the yellow parts
    "#dbdbdb",  # shading on the white parts
    "#3fca3b",  # outline of the green parts
    "#db862c",  # outline of the yellow parts
    "#b8b8b8",  # outline of the white parts
    "#434343",  # eye
    "#232222",  # pupil, hoodie strings
    "#aaebb1",  # highlights on the green parts
    "#e3311c",  # mouth
    "#cef2a0",  # highlights on the skin
    "#ef551a",  # tongue
]
NOTICE = ("<!-- Katie, the KDE mascot, designed by Tyson Tan (2026, for KDE's 30th birthday). "
          "Traced for the 3d-linux project with tools/trace_katie.py from "
          f"{URL} (also https://commons.wikimedia.org/wiki/"
          "File:KDE_mascot_Katie_for_KDE_30.png). License: CC BY-SA 4.0. -->\n")


def download() -> Image.Image:
    with urllib.request.urlopen(urllib.request.Request(
            URL, headers={"User-Agent": "3d-linux trace_katie.py"}), timeout=60) as response:
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256:
        sys.exit(f"the picture changed: sha256 {digest}, expected {SHA256}")
    return Image.open(io.BytesIO(data)).convert("RGBA")


def labels(picture: Image.Image) -> np.ndarray:
    """Palette index of every pixel, or -1 for the background."""
    palette = Image.new("P", (1, 1))
    rgb = [int(c[i:i + 2], 16) for c in PALETTE for i in (1, 3, 5)]
    palette.putpalette(rgb + rgb[:3] * (256 - len(PALETTE)))
    index = np.asarray(picture.convert("RGB").quantize(palette=palette,
                                                       dither=Image.Dither.NONE))
    index = index.astype(np.int16)
    index[index >= len(PALETTE)] = 0  # the padding of the PIL palette repeats PALETTE[0]
    index[np.asarray(picture)[..., 3] < 128] = -1
    return index


def shrink(index: np.ndarray) -> np.ndarray:
    """Scale down by a whole factor; every new pixel takes its most common label."""
    k = max(1, round(index.shape[0] / HEIGHT))
    h, w = index.shape[0] // k * k, index.shape[1] // k * k
    blocks = index[:h, :w].reshape(h // k, k, w // k, k)
    votes = np.stack([(blocks == n).sum(axis=(1, 3))
                      for n in range(-1, len(PALETTE))])
    return votes.argmax(axis=0).astype(np.int16) - 1


def figure_only(index: np.ndarray) -> np.ndarray:
    """Clear every piece that is not joined to the largest one (the sparkles)."""
    pieces, n = ndimage.label(index >= 0)
    sizes = ndimage.sum(np.ones_like(pieces), pieces, range(1, n + 1))
    out = index.copy()
    out[pieces != 1 + int(np.argmax(sizes))] = -1
    return out


def trace(index: np.ndarray) -> str:
    rgba = np.zeros((*index.shape, 4), dtype=np.uint8)
    for n, colour in enumerate(PALETTE):
        rgba[index == n] = [int(colour[i:i + 2], 16) for i in (1, 3, 5)] + [255]
    png = io.BytesIO()
    Image.fromarray(rgba).save(png, format="PNG")
    return vtracer.convert_raw_image_to_svg(
        png.getvalue(), img_format="png", colormode="color", hierarchical="stacked",
        mode="spline", filter_speckle=4, color_precision=8, layer_difference=1,
        corner_threshold=60, length_threshold=4.0, splice_threshold=45, path_precision=2)


def exact_colours(svg: str) -> str:
    """Every fill set to the nearest palette colour."""
    rgb = {c: np.array([int(c[i:i + 2], 16) for i in (1, 3, 5)]) for c in PALETTE}

    def snap(match: re.Match) -> str:
        fill = np.array([int(match[1][i:i + 2], 16) for i in (0, 2, 4)])
        return f'fill="{min(PALETTE, key=lambda c: np.abs(rgb[c] - fill).sum())}"'

    return re.sub(r'fill="#([0-9A-Fa-f]{6})"', snap, svg)


def main() -> None:
    index = figure_only(shrink(labels(download())))
    svg = exact_colours(trace(index))
    head, sep, body = svg.partition("<svg")
    OUT.write_text(head + NOTICE + sep + body, encoding="utf-8")
    print(f"wrote {OUT} ({index.shape[1]} x {index.shape[0]} px, {svg.count('<path')} paths)")


if __name__ == "__main__":
    main()
