"""Christmas tree ornaments: the drawing of a figure on both sides.

With one extruder, the face on the bed is all one colour. So an ornament is two halves,
printed side by side on one plate with the same colour changes, and glued back to back
(the two bed faces meet). The back half is turned over, so its outline must be the
mirror image of the front's:

- If the outline is symmetric (the KDE square, the Plasma disc), the back half is a copy
  of the front. Seen from behind, the drawing reads the right way round.
- Otherwise (Gentoo, Larry, Konqi) the back half is the front's mirror image, the only
  shape that lies exactly behind it. Seen from behind, the drawing is mirrored, as if you
  looked through the ornament.

More details:
- The halves use the figure's bands and colour map, at `ornament_h` instead of `height`,
  with a thinner body (`ornament_t`): the two bodies together make the core.
- A tab with a hole sits on top, straight above the centre of mass of the glued ornament,
  so it hangs upright. It is part of band 0 (the body colour) only: the drawing keeps its
  colours.
- Two blind sockets in the glued face take short pieces of 1.75 mm filament as dowels.
  They line the halves up while the glue sets.

2D frame: as in relief.py, x centred on the drawing (on the axis of a symmetric outline)
and y up, but nothing is cut: the drawing starts at y = 0. Print pose: the front face up,
z = 0 on the bed. The back half turns over about the y axis (x -> -x).
"""

from dataclasses import dataclass, replace
from functools import cache

import numpy as np
from build123d import CenterOf, Part, Plane, Pos, Rot
from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from . import params as P
from . import relief
from .figures import Figure

RING_W = P.lines(5)  # wall around the hanging hole (2.1 mm)
SOCKET_WALL = 1.5  # least material between a dowel socket and the edge of the body (mm)
# an outline is symmetric if no point of its edge lies farther than this from the edge of
# its mirror image (mm): then the two halves are the same
SYMMETRY = 0.05


@dataclass(frozen=True)
class OrnamentLayout:
    """One half of an ornament in 2D (the front half, mm)."""

    regions: dict[str, BaseGeometry]  # filament -> visible area of the drawing
    body: Polygon  # drawing + backing, without the tab
    tab: BaseGeometry  # the hanging tab, with its hole
    bands: list[BaseGeometry]  # printable footprint of every band; bands[0] has the tab
    hole: tuple[float, float, float]  # x, y and radius of the hanging hole
    sockets: tuple[tuple[float, float], ...]  # centres of the dowel sockets
    mirror_back: bool  # the back half is the mirror image (False: a copy of the front)
    centre: tuple[float, float]  # centre of mass of the glued ornament, tab included
    size: tuple[float, float]  # width and height, tab included

    @property
    def tilt(self) -> float:
        """How far the ornament hangs off upright (degrees)."""
        return hang_angle(self.hole, self.centre)


def hang_angle(hole: tuple[float, float, float], centre: tuple[float, float]) -> float:
    """How far an ornament with this hole and centre of mass hangs off upright (degrees).
    The hook rests on the top of the hole."""
    x, y, r = hole
    return float(np.degrees(np.arctan2(abs(centre[0] - x), y + r - centre[1])))


def as_ornament(fig: Figure) -> Figure:
    """The figure at the ornament's size and body thickness: the band functions of
    relief.py (band_z, colour_changes, ...) work on it unchanged."""
    return replace(fig, height=fig.ornament_h, base_t=fig.ornament_t)


def _tab(fig: Figure, body: Polygon, x: float) -> tuple[BaseGeometry, Polygon, float]:
    """The tab (hole not yet cut), the hole and the hole's height, for a hole above x.

    The ring around the hole (RING_W wide) sits on the highest point of the body below
    it, so the hole is always RING_W away from the drawing. A neck joins it to the body.
    """
    r = fig.hole_d / 2
    outer = r + RING_W
    strip = body.intersection(box(x - outer, -1e4, x + outer, 1e4))
    if strip.is_empty:
        raise ValueError(f"{fig.name}: nothing of the figure lies under the hanging point")
    top = strip.bounds[3]
    y = top + outer
    ring = Point(x, y).buffer(outer, quad_segs=32)
    neck = body.intersection(box(x - outer, top - outer, x + outer, top))
    tab = unary_union([ring, neck]).convex_hull
    return tab, Point(x, y).buffer(r, quad_segs=32), y


def _sockets(fig: Figure, body: Polygon, mirror_back: bool) -> tuple[tuple[float, float], ...]:
    """Two dowel sockets far apart, where both halves have one once glued: the lowest point
    inside the body and the point farthest from it; or, if the back half is a copy of the
    front, the rightmost point inside the body and its mirror image."""
    inner = relief.polygons(body.buffer(-(P.SOCKET_D / 2 + SOCKET_WALL)))
    if not inner:
        raise ValueError(f"{fig.name}: the ornament is too small for the dowel sockets")
    pts = np.array(max(inner, key=lambda p: p.area).exterior.coords)
    if mirror_back:
        a = pts[pts[:, 1].argmin()]
        b = pts[np.linalg.norm(pts - a, axis=1).argmax()]
    else:
        a = pts[pts[:, 0].argmax()]
        b = (-a[0], a[1])
    return tuple((float(x), float(y)) for x, y in (a, b))


def is_symmetric(body: BaseGeometry) -> bool:
    """The outline is its own mirror image across the vertical line through its middle.

    The largest gap counts (Hausdorff distance between the edges, holes included), not the
    average: one notch on a long edge makes the outline asymmetric.
    """
    x0, _, x1, _ = body.bounds
    mirror = affinity.scale(body, -1, 1, origin=((x0 + x1) / 2, 0))
    return body.boundary.hausdorff_distance(mirror.boundary) < SYMMETRY


@cache
def layout(fig: Figure) -> OrnamentLayout:
    view = as_ornament(fig)
    view.validate()
    regions, body = relief.artwork(view)
    mirror_back = not is_symmetric(body)
    if not mirror_back:  # the axis at x = 0: turned over, a copy lies exactly behind
        x0, _, x1, _ = body.bounds
        regions = {f: affinity.translate(g, -(x0 + x1) / 2) for f, g in regions.items()}
        body = affinity.translate(body, -(x0 + x1) / 2)
    bands = relief.colour_bands(view, body, regions)
    z = relief.band_z(view)
    plain = bands[0]
    # The glued ornament hangs with its centre of mass under the hole. With a mirrored
    # back, that is the centre of mass of one half. With a copy, the two halves' centres
    # lie on both sides of the axis, so the glued ornament's is on the axis.
    x = relief.centre_x(bands, z) if mirror_back else 0.0
    for _ in range(4):  # the tab moves the centre of mass a little: place it again
        tab, hole, y = _tab(view, body, x)
        joined = relief.polygons(unary_union([plain, tab]))
        if len(joined) != 1:  # never drop part of a figure silently
            raise ValueError(f"{fig.name}: the hanging tab does not join the body")
        bands[0] = relief._tidy(joined[0].difference(hole))  # not simplified: see layout()
        cx, cy = relief.centre(bands, z)
        com = (cx if mirror_back else 0.0, cy)
        if abs(com[0] - x) < 0.01:
            break
        x = com[0]
    else:  # the tab, the hole and the centre of mass would not belong together
        raise ValueError(f"{fig.name}: the hanging tab does not settle over the centre of mass")
    x0, y0, x1, y1 = bands[0].bounds
    return OrnamentLayout(regions, body, tab.difference(hole), bands, (x, y, fig.hole_d / 2),
                          _sockets(fig, body, mirror_back), mirror_back, com,
                          (x1 - x0, y1 - y0))


def colour_changes(fig: Figure) -> list[tuple[float, str]]:
    """The M600s of the ornament plate (the same for both halves)."""
    return relief.colour_changes(as_ornament(fig))


def _back(part: Part, lay: OrnamentLayout) -> Part:
    """The back half's copy of a front part: mirrored across x = 0, or the same."""
    return part.mirror(Plane.YZ) if lay.mirror_back else Pos() * part


@cache
def band_parts(fig: Figure, back: bool = False) -> tuple[Part, ...]:
    """One solid per band of one half, in the print pose."""
    lay = layout(fig)
    if back:  # no booleans: the same solids, mirrored or copied
        return tuple(_back(p, lay) for p in band_parts(fig))
    z = relief.band_z(as_ornament(fig))
    sockets = unary_union([Point(p).buffer(P.SOCKET_D / 2, quad_segs=16) for p in lay.sockets])
    # band 0 in two slabs: the sockets go up to SOCKET_DEPTH from the glued face
    body = relief.slab(lay.bands[0].difference(sockets), 0.0, P.SOCKET_DEPTH)
    body = body + relief.slab(lay.bands[0], P.SOCKET_DEPTH, z[0][1])
    return (body, *(relief.slab(relief.inset(g, k), z0, z1)
                    for k, (g, (z0, z1)) in enumerate(zip(lay.bands[1:], z[1:]), start=1)))


@cache
def make_half(fig: Figure, back: bool = False) -> Part:
    """One half of the ornament in the print pose: front face up, the tab towards +y."""
    if back:
        return _back(make_half(fig), layout(fig))
    return relief.fuse(band_parts(fig))


def mass_centre(fig: Figure) -> tuple[float, float]:
    """x and y of the centre of mass of the glued ornament, measured on the solids of both
    halves (sockets included), the back half turned over (x -> -x). layout() places the hole
    with the 2D centre of the bands; this checks it."""
    total = mx = my = 0.0
    for side, half in ((1, band_parts(fig)), (-1, band_parts(fig, back=True))):
        for part in half:
            v, c = part.volume, part.center(CenterOf.MASS)
            total, mx, my = total + v, mx + v * side * c.X, my + v * c.Y
    return mx / total, my / total


def coloured(fig: Figure) -> list[tuple[Part, str]]:
    """(band solid, filament) pairs of the glued ornament, hanging: the front faces -y,
    the glued faces are at y = 0 and the tab is on top. For previews."""
    front = band_parts(fig)
    back = [Rot(0, 180, 0) * p for p in band_parts(fig, back=True)]  # turned over
    return [(relief.standing(p), f) for half in (front, back) for p, f in zip(half, fig.bands)]
