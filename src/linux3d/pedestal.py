"""Pedestal: a plinth with a slot for the standee's tenon and raised lettering on top.

It prints standing up, as it stands. The lettering sits on the top face in front of the
figure and can start with an M600, so it comes out in a second colour.

Assembly frame: the pedestal's top face is at z = 0, the figure's back face is at y = 0,
and its front faces -y (towards the viewer). `print_pose` lifts the pedestal onto the bed.
"""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

from build123d import (
    Align,
    Box,
    Part,
    Pos,
    RectangleRounded,
    Text,
    extrude,
)

from . import params as P
from .figures import Figure
from .relief import layout, thickness

FONT = Path(__file__).resolve().parent / "fonts" / "NotoSans-Bold.ttf"
if not FONT.is_file():  # build123d would silently fall back to a system font
    raise FileNotFoundError(f"bundled font missing: {FONT}")
CHAMFER = P.layers(8)  # 45° chamfer around the top edge
CORNER = 4.0  # corner radius of the footprint
SIDE_WALL = 5.0  # least material beside the slot (mm)
BACK = 7.0  # least material behind the slot (mm)
TEXT_GAP = 2.0  # lettering <-> chamfer and lettering <-> figure (mm)


@dataclass(frozen=True)
class Size:
    """Footprint, height and slot of a pedestal (assembly frame)."""

    x0: float
    x1: float
    y0: float  # front
    y1: float  # back
    h: float
    slot: tuple[float, float, float, float]  # x0, x1, y0, y1
    slot_depth: float


def size(fig: Figure, clr: float = P.CLR_SLOT) -> Size:
    lay = layout(fig)
    slot = (lay.foot[0] - clr, lay.foot[1] + clr, -fig.base_t - clr, clr)
    width = lay.size[0]
    half = max(fig.pedestal_w / 2 or 0.36 * width, abs(slot[0]) + SIDE_WALL + CHAMFER,
               abs(slot[1]) + SIDE_WALL + CHAMFER)
    y1 = slot[3] + BACK + CHAMFER
    # never thinner in front of the slot than beside it, whatever pedestal_d says
    depth = max(fig.pedestal_d or max(0.36 * fig.height, 26.0),
                y1 - slot[2] + SIDE_WALL + CHAMFER)
    slot_depth = P.snap_up(fig.tenon_h + P.SLOT_FLOOR_GAP)  # validate() checks the floor
    return Size(-half, half, y1 - depth, y1, fig.pedestal_h, slot, slot_depth)


def _plinth(s: Size) -> Part:
    """Rounded block, top at z = 0, with a 45° chamfer around the top edge."""
    w, d = s.x1 - s.x0, s.y1 - s.y0
    centre = Pos((s.x0 + s.x1) / 2, (s.y0 + s.y1) / 2, -s.h)
    lower = extrude(RectangleRounded(w, d, CORNER), s.h - CHAMFER, dir=(0, 0, 1))
    upper = Pos(0, 0, s.h - CHAMFER) * extrude(RectangleRounded(w, d, CORNER), CHAMFER,
                                              dir=(0, 0, 1), taper=45)
    return centre * (lower + upper)


def lettering(fig: Figure, s: Size) -> Part | None:
    """Raised text on the top face, between the front chamfer and the figure."""
    if not fig.title:
        return None
    y_front = s.y0 + CHAMFER + TEXT_GAP
    y_back = -thickness(fig) - TEXT_GAP
    room_w = s.x1 - s.x0 - 2 * (CHAMFER + TEXT_GAP)
    room_d = y_back - y_front
    if room_d < 4.0:
        raise ValueError(f"{fig.name}: no room for the lettering; make pedestal_d larger")
    probe = Text(fig.title, fig.text_size, font_path=str(FONT))
    bb = probe.bounding_box()
    scale = min(1.0, room_w / bb.size.X, room_d / bb.size.Y)
    text = Text(fig.title, fig.text_size * scale, font_path=str(FONT),
                align=(Align.CENTER, Align.CENTER))
    return Pos(0, (y_front + y_back) / 2, 0) * extrude(text, fig.text_h, dir=(0, 0, 1))


@cache
def make_pedestal(fig: Figure, clr: float = P.CLR_SLOT) -> Part:
    """The pedestal in the assembly frame (top face at z = 0)."""
    s = size(fig, clr)
    x0, x1, y0, y1 = s.slot
    body = _plinth(s)
    body -= Pos((x0 + x1) / 2, (y0 + y1) / 2, -s.slot_depth / 2 + 0.5) * Box(
        x1 - x0, y1 - y0, s.slot_depth + 1)
    text = lettering(fig, s)
    return body + text if text is not None else body


def print_pose(fig: Figure, part: Part) -> Part:
    """Assembly frame -> on the bed (bottom face at z = 0)."""
    return Pos(0, 0, fig.pedestal_h) * part


def text_change(fig: Figure) -> tuple[float, str] | None:
    """The M600 before the first layer of the lettering, or None."""
    if not fig.title or not fig.text_colour or fig.text_colour == fig.pedestal_colour:
        return None
    return P.layer_top(fig.pedestal_h), fig.text_colour


def coloured(fig: Figure) -> list[tuple[Part, str]]:
    """(part, filament) pairs in the assembly frame, for renders and previews."""
    whole = make_pedestal(fig)
    if text_change(fig) is None:  # no lettering, or lettering in the pedestal colour
        return [(whole, fig.pedestal_colour)]
    top = Pos(0, 0, fig.text_h / 2) * Box(1e3, 1e3, fig.text_h)
    return [(whole - top, fig.pedestal_colour), (whole & top, fig.text_colour)]
