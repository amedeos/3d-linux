"""The filaments on the shelf, and the PrusaSlicer material profiles.

Only these colours exist for the colour mapping: every SVG colour ends up as one of them.
The hex values are close to Prusament PETG and are used for the 3MF object colours, the
M600 entries and the renders. Change them, or add colours, here.
"""

FILAMENTS = {
    "black": "#1c1a1e",
    "white": "#ece8dc",
    "red": "#c62127",
    "gold": "#e8b10e",  # yellow gold
    "green": "#3e9b35",
    "orange": "#f07318",
    "violet": "#5e4a9c",
    "grey": "#7b7c80",
    "blue": "#1f6fd1",
}

# PrusaSlicer filament profiles for the Prusa MK4 Input Shaper printer profile
MATERIALS = {
    "petg": "Prusament PETG @PGIS",  # default
    "pla": "Prusament PLA @PGIS",
}
DEFAULT_MATERIAL = "petg"


def hex_rgb(colour: str) -> tuple[float, float, float]:
    """'#rrggbb' or '#rgb' -> (r, g, b) in 0..1."""
    h = colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def rgb(name: str) -> tuple[float, float, float]:
    return hex_rgb(FILAMENTS[name])


def _lab(c: tuple[float, float, float]) -> tuple[float, float, float]:
    """sRGB (0..1) -> CIELAB (D65)."""
    lin = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    x = (0.4124 * lin[0] + 0.3576 * lin[1] + 0.1805 * lin[2]) / 0.95047
    y = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    z = (0.0193 * lin[0] + 0.1192 * lin[1] + 0.9505 * lin[2]) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def nearest(colour: str, choices: list[str] | None = None) -> str:
    """The filament (name) closest to an SVG colour, by CIELAB distance."""
    target = _lab(hex_rgb(colour))
    names = choices or list(FILAMENTS)

    def dist(name: str) -> float:
        return sum((a - b) ** 2 for a, b in zip(target, _lab(rgb(name))))

    return min(names, key=dist)
