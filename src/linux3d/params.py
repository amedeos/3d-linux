"""Printer and process constants shared by every figure (millimetres).

Every flat horizontal face must sit on a layer boundary when the part lies in its print
position, and thin walls are a whole number of extrusion lines (see `lines()` and
tests/test_layers.py). The sizes of each figure live in `figures.py`.
"""

from math import ceil, pi

# --- printer / process: Prusa MK4, 0.4 mm nozzle, PrusaSlicer "0.20mm STRUCTURAL" -----
BED = (250.0, 210.0, 220.0)  # Prusa MK4 print volume
NOZZLE = 0.4
LAYER = 0.2  # layer height
FIRST_LAYER = 0.2  # first layer height
LINE_W = 0.45  # extrusion width (perimeters and infill)
# centre distance of two touching lines, as PrusaSlicer computes it
LINE_SPACING = LINE_W - LAYER * (1 - pi / 4)
MIN_STROKE = 0.85 * LINE_W  # Arachne drops walls thinner than this (min_bead_width)
MIN_GAP = LINE_W  # narrower gaps and grooves close up


def lines(n: int) -> float:
    """Width of a wall made of n touching extrusion lines."""
    return (n - 1) * LINE_SPACING + LINE_W


def layers(n: int) -> float:
    """Height of n layers (the first layer included)."""
    return round(FIRST_LAYER + (n - 1) * LAYER, 6) if n > 0 else 0.0


def layer_top(z: float) -> float:
    """Top (print_z) of the first layer that starts at or above height z."""
    if z <= 1e-9:
        return FIRST_LAYER
    k = ceil((z - FIRST_LAYER) / LAYER - 1e-9) + 1
    return round(FIRST_LAYER + k * LAYER, 6)


def snap_up(z: float) -> float:
    """Smallest layer boundary at or above z (boundaries: 0, FIRST_LAYER, + n * LAYER)."""
    if z <= FIRST_LAYER:
        return 0.0 if z <= 1e-9 else FIRST_LAYER
    return round(FIRST_LAYER + ceil((z - FIRST_LAYER) / LAYER - 1e-9) * LAYER, 6)


def on_grid(z: float) -> bool:
    return abs(z - round(z / LAYER) * LAYER) < 1e-3


# --- standee -----------------------------------------------------------------------
BASE_T = layers(12)  # body of a standee (band 0), and so the tenon thickness: 2.4 mm
BAND_T = layers(4)  # every further colour band (0.8 mm); use 6 layers if white shows grey

# --- standee <-> pedestal fit (tune these after printing the slot gauge) -------------
CLR_SLOT = 0.10  # pedestal slot <-> tenon, per side. 0.10 fitted well in PETG on an MK4
#                  (the nail gauge of the halloween coffin).
SLOT_GAUGE = (0.05, 0.10, 0.15, 0.20)  # clearances of the four slots of the slot gauge
SLOT_FLOOR_GAP = 2 * LAYER  # the tenon stops this far above the slot floor
PEDESTAL_FLOOR = 2.0  # least material under the slot (mm)
