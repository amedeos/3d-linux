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
- Or, with `hang_from`, the hole goes through a shape of the drawing (Znurt's antenna
  ball): no tab, and the shape and the body around it become an eyelet in the shape's
  colour. The hole moves sideways from the middle of the shape towards the centre of mass,
  as far as the eyelet allows (with a copied back, it must lie on the axis).
- Two blind sockets in the glued face take short pieces of 1.75 mm filament as dowels.
  They line the halves up while the glue sets.

2D frame: as in relief.py, x centred on the drawing (on the axis of a symmetric outline)
and y up, but nothing is cut: the drawing starts at y = 0. Print pose: the front face up,
z = 0 on the bed. The back half turns over about the y axis (x -> -x).
"""

import math
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
MAX_TILT = 1.0  # degrees: the most an ornament may hang off upright
# the eyelet of `hang_from` reaches this far past `margin` (mm), so it meets the edge of
# the body instead of stopping a hair short of it
EYELET_REACH = 0.05


@dataclass(frozen=True)
class OrnamentLayout:
    """One half of an ornament in 2D (the front half, mm)."""

    regions: dict[str, BaseGeometry]  # filament -> visible area of the drawing
    body: Polygon  # drawing + backing, without the tab
    tab: BaseGeometry  # the hanging tab, with its hole (empty with `hang_from`)
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


def _sockets(fig: Figure, body: BaseGeometry,
             mirror_back: bool) -> tuple[tuple[float, float], ...]:
    """Two dowel sockets far apart, where both halves have one once glued: the lowest point
    inside the body and the point farthest from it; or, if the back half is a copy of the
    front, the rightmost point inside the body and its mirror image.

    If the lowest point and the farthest from it are less than half the body's size apart
    (the bottom of Znurt's wide saucer and one end), the first socket goes to the point
    farthest from the second instead (the other end).
    """
    inner = relief.polygons(body.buffer(-(P.SOCKET_D / 2 + SOCKET_WALL)))
    if not inner:
        raise ValueError(f"{fig.name}: the ornament is too small for the dowel sockets")
    pts = np.array(max(inner, key=lambda p: p.area).exterior.coords)
    if mirror_back:
        a = pts[pts[:, 1].argmin()]
        b = pts[np.linalg.norm(pts - a, axis=1).argmax()]
        x0, y0, x1, y1 = body.bounds
        if np.linalg.norm(b - a) < 0.5 * max(x1 - x0, y1 - y0):
            a = pts[np.linalg.norm(pts - b, axis=1).argmax()]
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


def _settle(fig: Figure, what: str, x: float, place, step, z, mirror_back: bool):
    """Place the hanging hole again until it lies over the centre of mass of the glued
    ornament: what is placed moves the centre of mass a little.

    place(x) gives (bands, extra) with the hole above x; step(x, cx) gives the next x for
    the centre of mass at cx. Returns x, the bands, the centre of mass and extra.
    """
    for _ in range(4):
        bands, extra = place(x)
        cx, cy = relief.centre(bands, z)
        # With a mirrored back, the glued ornament's centre of mass is that of one half.
        # With a copy, the two halves' centres lie on both sides of the axis: it is on it.
        com = (cx if mirror_back else 0.0, cy)
        nxt = step(x, com[0])
        if abs(nxt - x) < 0.01:
            return x, bands, com, extra
        x = nxt
    # the hole and the centre of mass would not belong together
    raise ValueError(f"{fig.name}: {what} does not settle over the centre of mass")


def _room(area: BaseGeometry, x: float, y: float) -> float:
    """How far a point lies inside an area: its distance to the nearest edge (0 outside)."""
    p = Point(x, y)
    return area.boundary.distance(p) if area.contains(p) else 0.0


def _towards(area: BaseGeometry, x: float, y: float, target: float, need: float) -> float:
    """x moved along the line at height y towards target, as far as the point keeps `need`
    of the area all round it. The start must have that room."""
    def fits(t: float) -> bool:
        return _room(area, x + t * (target - x), y) >= need - 1e-9

    if fits(1.0):
        return target
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if fits(mid) else (lo, mid)
    return x + lo * (target - x)


def _wall_error(fig: Figure, wall: float, where: str = "") -> ValueError:
    """The error for a wall around a hang_from hole thinner than RING_W. The wall is shown
    rounded down and RING_W rounded up, so the two numbers never look the same."""
    return ValueError(f"{fig.name}: a {fig.hole_d:g} mm hole through {fig.hang_from}{where} "
                      f"leaves a wall of only {math.floor(wall * 100) / 100:.2f} mm in its "
                      f"colour (at least {math.ceil(RING_W * 100) / 100:.2f}): make "
                      "ornament_h larger or hole_d smaller, or use the tab (hang_from='')")


def _hung_from_shape(fig: Figure, view: Figure, regions: dict[str, BaseGeometry],
                     body: Polygon, mirror_back: bool, shift: float) -> OrnamentLayout:
    """The layout of an ornament that hangs from a shape of its drawing (`hang_from`).

    No tab. The shape and the body within `margin` of it become an eyelet in the shape's
    colour, but the eyelet takes over only the body colour (the backing, and parts of the
    drawing in the body colour such as Znurt's antenna): the other colours of the drawing
    keep theirs. The hole, with RING_W of wall all round, must lie inside the eyelet, so
    the wall around it is the shape's colour in every band up to the shape's, and no
    higher band comes near it: cutting the hole from the cleaned bands leaves no sliver.

    The hole starts at the middle of the shape and moves sideways towards the centre of
    mass, as far as the eyelet allows. With a copied back (a symmetric outline) it must lie
    on the axis, or the halves' holes would not line up. Errors: the hole would not lie in
    the shape (a ring, or a shape off the axis), the wall is too thin, the hole is not above
    the centre of mass, or the ornament would still hang more than MAX_TILT off upright.
    """
    key = fig.hang_from
    filament, shape = relief.shape_area(view, key)
    shape = affinity.translate(shape, shift)
    y = shape.centroid.y
    x = shape.centroid.x if mirror_back else 0.0  # a copied back: on the axis
    # the cheap checks first: colour_bands() is the costly part
    if not shape.contains(Point(x, y)):
        why = ("its middle lies outside the shape (a ring?)" if mirror_back else
               "it does not reach the axis of the symmetric outline, where the hole must lie "
               "for the halves' holes to line up")
        raise ValueError(f"{fig.name}: the hole cannot go through {key}: {why}; hang it from "
                         "a shape the hole can go through, or use the tab (hang_from='')")
    body_colour = fig.bands[0]
    others = unary_union([g for f, g in regions.items() if f not in (filament, body_colour)])
    reach = shape.buffer(fig.margin + EYELET_REACH).intersection(body)
    eyelet = unary_union([shape, reach.difference(others)])
    r = fig.hole_d / 2
    need = r + RING_W  # from the middle of the hole to the edge of the eyelet
    if _room(eyelet, x, y) < need - 1e-9:
        raise _wall_error(fig, max(0.0, _room(eyelet, x, y) - r))
    regions = dict(regions)
    if body_colour != filament:
        regions[body_colour] = regions[body_colour].difference(eyelet)
    regions[filament] = unary_union([regions[filament], eyelet])
    plain = relief.colour_bands(view, body, regions)  # once: the hole only cuts them
    z = relief.band_z(view)

    def place(x: float):
        hole = Point(x, y).buffer(r, quad_segs=32)
        return [relief._tidy(b.difference(hole)) for b in plain], hole  # not simplified

    if mirror_back:
        x, bands, com, hole = _settle(fig, f"the hole through {key}", x, place,
                                      lambda x, cx: _towards(eyelet, x, y, cx, need), z, True)
    else:  # on the axis, where the glued ornament's centre of mass is
        bands, hole = place(0.0)
        com = (0.0, relief.centre(bands, z)[1])
    if y - r <= com[1]:
        raise ValueError(f"{fig.name}: the hole through {key} does not lie above the centre "
                         "of mass: use the tab (hang_from='')")
    tilt = hang_angle((x, y, r), com)
    if tilt > MAX_TILT:
        raise ValueError(f"{fig.name}: hung from {key}, it would hang {tilt:.1f}° off upright "
                         f"(at most {MAX_TILT:g}°): the shape is not above the centre of "
                         "mass; use the tab (hang_from='')")
    x0, y0, x1, y1 = bands[0].bounds
    return OrnamentLayout(regions, body, Polygon(), bands, (x, y, r),
                          _sockets(fig, body.difference(hole), mirror_back), mirror_back, com,
                          (x1 - x0, y1 - y0))


@cache
def layout(fig: Figure) -> OrnamentLayout:
    view = as_ornament(fig)
    view.validate()
    regions, body = relief.artwork(view)
    mirror_back = not is_symmetric(body)
    shift = 0.0
    if not mirror_back:  # the axis at x = 0: turned over, a copy lies exactly behind
        x0, _, x1, _ = body.bounds
        shift = -(x0 + x1) / 2
        regions = {f: affinity.translate(g, shift) for f, g in regions.items()}
        body = affinity.translate(body, shift)
    if fig.hang_from:
        return _hung_from_shape(fig, view, regions, body, mirror_back, shift)
    bands = relief.colour_bands(view, body, regions)
    z = relief.band_z(view)

    def place(x: float):
        tab, hole, y = _tab(view, body, x)
        joined = relief.polygons(unary_union([bands[0], tab]))
        if len(joined) != 1:  # never drop part of a figure silently
            raise ValueError(f"{fig.name}: the hanging tab does not join the body")
        # not simplified: see relief.layout()
        return [relief._tidy(joined[0].difference(hole)), *bands[1:]], (tab, hole, y)

    start = relief.centre_x(bands, z) if mirror_back else 0.0
    x, placed, com, (tab, hole, y) = _settle(fig, "the hanging tab", start, place,
                                             lambda x, cx: cx, z, mirror_back)
    x0, y0, x1, y1 = placed[0].bounds
    return OrnamentLayout(regions, body, tab.difference(hole), placed, (x, y, fig.hole_d / 2),
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
