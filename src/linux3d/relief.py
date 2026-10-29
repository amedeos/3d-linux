"""From an SVG drawing to a printable standee: colour bands, foot and tenon.

All the 2D work happens in shapely (fast and robust): colour regions, the body, the cut
that gives the figure a flat foot, the tenon, and the cleanup that makes every band
printable with 0.45 mm lines. build123d only extrudes the finished bands.

2D frame ("standing"): x is centred on the drawing, y points up, and the foot is cut at
y = 0. The tenon hangs below y = 0, inside the pedestal.

Print pose (`make_figure`): the same x and y on the bed, the front face up (+z).
"""

import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
import shapely
from build123d import Face, Part, Pos, Rot, Wire, extrude
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from . import params as P
from . import svg
from .figures import DROP, Figure
from .filaments import nearest

CRUMB = 0.05  # mm2: smaller pieces of a band are left out
SPECK = 0.3  # mm2: thinner-than-a-line gaps this small are filled, not widened
HAIR = 0.025  # mm: cracks between two bands narrower than 2 * HAIR are boolean noise
SIMPLIFY = 0.01  # mm: polyline tolerance of the colour regions
# Corners a fraction of a micron apart give edges that short in the solid, and zero-area
# triangles in the STL (Katie's was not watertight). So every corner of a solid lies on a
# GRID (mm), and band k's solid is k * INSET (mm) inside the band's edge: a band's edge
# never touches the edge of the band below, and the boolean has no edges to intersect
# where the two meet. 10 um at most, far below what a 0.4 mm nozzle can show.
GRID = 1e-3
INSET = 2 * GRID
# Standing steady: the centre of mass must lie this far inside the support, or the tenon
# carries the whole weight on one side and the figure leans by the slot clearance.
SUPPORT_MARGIN = 3.0  # mm
MIN_POST = 4.0  # mm: the narrowest post (9 lines)
MAX_POST = 0.25  # the tallest post, as a share of the figure height


@dataclass(frozen=True)
class Layout:
    """The figure in 2D (standing frame, mm)."""

    regions: dict[str, BaseGeometry]  # filament -> visible area of the drawing
    body: BaseGeometry  # band 0 above the foot (drawing + backing, cut flat)
    tenon: Polygon  # below y = 0
    bands: list[BaseGeometry]  # printable footprint of every band; bands[0] has the tenon
    foot: tuple[float, float]  # x range of every contact at y = 0 (the tenon's width)
    cut: float  # how much of the drawing's bottom was cut off for the foot (mm)
    size: tuple[float, float]  # width and height of the body
    centre_x: float  # centre of mass of the standee above the foot
    post: tuple[float, float, float] | None  # x0, x1, top of the post added for support

    @property
    def beside(self) -> float:
        """How far the centre of mass lies outside the support (0 = over it)."""
        return max(0.0, self.foot[0] - self.centre_x, self.centre_x - self.foot[1])


@cache
def _shapes(path: Path) -> tuple[svg.Shape2D, ...]:
    return tuple(svg.load(path))


def polygons(geom: BaseGeometry) -> list[Polygon]:
    """Every polygon inside a geometry (collections included)."""
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    return [p for g in getattr(geom, "geoms", []) for p in polygons(g)]


def _tidy(geom: BaseGeometry) -> BaseGeometry:
    """Remove zero-width spikes and cracks, and pieces and holes smaller than CRUMB: the
    leftovers of the booleans that give degenerate faces."""
    eps = 1e-3
    geom = geom.buffer(eps, join_style="mitre").buffer(-2 * eps, join_style="mitre").buffer(
        eps, join_style="mitre")
    keep = [Polygon(p.exterior, [h for h in p.interiors if Polygon(h).area >= CRUMB])
            for p in polygons(geom) if p.area >= CRUMB]
    return unary_union(keep) if keep else Polygon()


def _clean(geom: BaseGeometry) -> BaseGeometry:
    """`_tidy`, then fewer points (the simplification moves edges by up to SIMPLIFY)."""
    return _tidy(geom).simplify(SIMPLIFY)


def opening(geom: BaseGeometry, r: float) -> BaseGeometry:
    """Remove every part thinner than 2 r (morphological opening).

    GEOS can, rarely, return a buffer whose rings cross (Konqi at 145 mm), and the next
    boolean then fails. Such a result is repaired: overlapping shells are joined.
    """
    if geom.is_empty:
        return geom
    out = geom.buffer(-r, join_style="round").buffer(r, join_style="round")
    return out if out.is_valid else shapely.make_valid(out, method="structure",
                                                       keep_collapsed=False)


def drawing(fig: Figure) -> dict[str, BaseGeometry]:
    """Filament -> visible area of the drawing, scaled to the figure height (y up)."""
    cmap = fig.colour_map()
    kept, targets = [], {}
    for s in _shapes(fig.svg_path):
        target = cmap.get(s.key) or cmap.get(s.colour)
        if target == DROP or (target is None and s.opacity < fig.min_opacity):
            continue
        kept.append(s)
        targets[s.index] = target
    shown = svg.visible(kept)
    x0, y0, x1, y1 = unary_union([s.geom for s in shown]).bounds
    k = fig.height / (y1 - y0)
    out: dict[str, list] = {}
    for s in shown:
        filament = targets[s.index] or nearest(s.colour, list(fig.bands))
        g = affinity.affine_transform(s.geom, [k, 0, 0, k, -k * (x0 + x1) / 2, -k * y0])
        out.setdefault(filament, []).append(g)
    return {f: shapely.make_valid(unary_union(gs).simplify(SIMPLIFY)) for f, gs in out.items()}


def _backing(fig: Figure, art: BaseGeometry) -> BaseGeometry:
    m = fig.margin
    if fig.backing == "outline":
        body = art.buffer(m, join_style="round") if m > 0 else art
    elif fig.backing == "hull":
        body = art.convex_hull.buffer(m, join_style="round")
    elif fig.backing == "circle":
        # minimum_bounding_circle is a 32-gon: rebuild a smooth circle from its centre
        centre = shapely.minimum_bounding_circle(art).centroid
        body = Point(centre).buffer(shapely.minimum_bounding_radius(art) + m, quad_segs=64)
    else:  # rounded_rect
        x0, y0, x1, y1 = art.bounds
        c = min(fig.corner, (x1 - x0) / 2 + m, (y1 - y0) / 2 + m)
        body = box(x0 - m + c, y0 - m + c, x1 + m - c, y1 + m - c).buffer(c, quad_segs=32)
    body = opening(body, P.MIN_STROKE / 2)
    parts = polygons(_clean(body))
    if len(parts) != 1:
        raise ValueError(f"{fig.name}: the body falls apart into {len(parts)} pieces; "
                         "use backing='hull', 'circle' or 'rounded_rect', or a larger margin")
    return parts[0]


def chord(geom: BaseGeometry, y: float) -> list[tuple[float, float]]:
    """The x ranges where a horizontal line at height y crosses a geometry, left to right."""
    x0, _, x1, _ = geom.bounds
    cut = geom.intersection(LineString([(x0 - 1, y), (x1 + 1, y)]))
    lines = [g for g in getattr(cut, "geoms", [cut]) if g.geom_type == "LineString"]
    return sorted((g.bounds[0], g.bounds[2]) for g in lines if g.length > 0)


def _with_bar(body: BaseGeometry, x0: float, x1: float, y0: float, y1: float) -> Polygon:
    """The body with a block of its own colour added (a ground bar or a post)."""
    out = polygons(unary_union([body, box(x0, y0, x1, y1)]))
    if len(out) != 1:  # never drop part of a figure silently
        raise ValueError(f"a support block at x {x0:.1f}..{x1:.1f} does not join the body")
    return out[0]


def _foot(fig: Figure, body: Polygon) -> tuple[float, tuple[float, float]]:
    """Height of the cut that gives a flat contact of at least min_foot, and its x range.

    The first cut that reaches min_foot wins. If none does within max_cut of the height,
    the cut with the widest contact wins.
    """
    y0 = body.bounds[1]
    best = (0.0, (0.0, 0.0), 0.0)
    # steps of 0.1 mm (the foot does not have to be on any grid); start just above the
    # bottom, so that a flat bottom tilted by the simplification still counts as flat
    limit = fig.max_cut * fig.height
    c = 2 * SIMPLIFY
    while c <= limit + 1e-9:
        segs = chord(body, y0 + c)
        width = sum(b - a for a, b in segs)
        if width > best[2]:
            best = (c, (segs[0][0], segs[-1][1]), width)
            if width >= fig.min_foot:
                break
        c = round(c + 0.1, 6)
    if best[2] <= 0:
        raise ValueError(f"{fig.name}: no flat foot found")
    return best[0], best[1]


def centre(bands: list[BaseGeometry], z: list[tuple[float, float]]) -> tuple[float, float]:
    """x and y of the centre of mass of stacked bands (area times thickness)."""
    weights = [(b.area * (z1 - z0), b.centroid) for b, (z0, z1) in zip(bands, z)
               if not b.is_empty]
    total = sum(w for w, _ in weights)
    return (sum(w * c.x for w, c in weights) / total, sum(w * c.y for w, c in weights) / total)


def centre_x(bands: list[BaseGeometry], z: list[tuple[float, float]]) -> float:
    """x of the centre of mass of stacked bands."""
    return centre(bands, z)[0]


def _post(fig: Figure, body: Polygon, foot: tuple[float, float],
          com: float) -> tuple[float, float, float] | None:
    """Where a post must go so that the centre of mass lies over the support, or None.

    The post goes under the lowest part of the figure beyond the centre of mass (Konqi's
    raised foot), as wide as that part 1 mm above its lowest point, at least MIN_POST.
    """
    lo, hi = foot
    m = SUPPORT_MARGIN
    if lo + m <= com <= hi - m:
        return None
    x0, _, x1, _ = body.bounds
    xs = np.arange(x0 + 0.25, x1, 0.5)
    xs = xs[xs <= com - m] if com < lo + m else xs[xs >= com + m]
    lowest = None
    for x in xs:
        column = body.intersection(LineString([(x, -1.0), (x, 1e4)]))
        if not column.is_empty and (lowest is None or column.bounds[1] < lowest[1]):
            lowest = (x, column.bounds[1])
    side = abs(com - (lo if com < lo else hi))
    if lowest is None or lowest[1] > MAX_POST * fig.height:
        low = f"the lowest is {lowest[1]:.1f} mm up" if lowest else "there is nothing there"
        raise ValueError(
            f"{fig.name}: the centre of mass lies {side:.1f} mm beside the foot, and no part "
            f"of the figure beyond it is low enough for a post ({low}). Set support=False "
            f"to accept a lean of up to {lean_limit(fig):.1f}° in the slot, or change "
            "min_foot or ground")
    x, y = lowest
    top = y + 1.0  # the post reaches 1 mm into the part
    a, b = next(((a, b) for a, b in chord(body, top) if a - 1e-6 <= x <= b + 1e-6), (x, x))
    if b - a < MIN_POST:
        a, b = (a + b) / 2 - MIN_POST / 2, (a + b) / 2 + MIN_POST / 2
    return a, b, top


def lean_limit(fig: Figure) -> float:
    """The largest lean (degrees) the slot allows a figure whose centre of mass lies beside
    its foot: it pivots on the foot edge until the tenon meets one wall."""
    return math.degrees(math.atan2(P.CLR_SLOT, fig.tenon_h))


def _thin(geom: BaseGeometry, r: float) -> BaseGeometry:
    """The parts of a geometry narrower than 2 r."""
    return geom.difference(opening(geom, r)) if not geom.is_empty else geom


def artwork(fig: Figure) -> tuple[dict[str, BaseGeometry], Polygon]:
    """The colour regions and the body (drawing + backing), scaled, y up, not cut."""
    regions = drawing(fig)
    art = unary_union(list(regions.values()))
    if fig.background:
        filled = unary_union([Polygon(p.exterior) for p in polygons(art)])
        holes = filled.difference(art)
        if not holes.is_empty:
            regions[fig.background] = unary_union([regions.get(fig.background, Polygon()),
                                                   holes])
        art = filled
    return regions, _backing(fig, art)


def colour_bands(fig: Figure, body: BaseGeometry,
                 regions: dict[str, BaseGeometry]) -> list[BaseGeometry]:
    """The printable footprint of every band over a body: nested, with raised parts at least
    MIN_STROKE wide and grooves at least MIN_GAP wide."""
    bands = [opening(body, P.MIN_STROKE / 2)]
    for k in range(1, len(fig.bands)):
        wanted = unary_union([regions[f] for f in fig.bands[k:] if f in regions])
        fk = opening(wanted.intersection(bands[k - 1]), P.MIN_STROKE / 2)
        # widen grooves that would close up (e.g. Larry's thin black outlines). Only the
        # lower colours count: a hairline between two cleaned bands is not a groove.
        thin = _thin(bands[k - 1].difference(wanted), P.MIN_GAP / 2)
        # slivers between neighbouring shapes of the drawing: fill them, but only where
        # they touch the band (a lone speck would become a raised sliver of its own)
        specks = [p for p in polygons(thin) if p.area < SPECK and p.distance(fk) < 1e-6]
        grooves = [p for p in polygons(thin) if p.area >= SPECK]
        if specks:
            fk = unary_union([fk, *specks]).intersection(bands[k - 1])
        if grooves:
            fk = fk.difference(unary_union(grooves).buffer(P.MIN_GAP / 2))
        fk = _clean(opening(fk, P.MIN_STROKE / 2)).intersection(bands[k - 1])
        # opening and simplifying move shared edges by a hair. Fill the cracks of the lower
        # colour that are narrower than 2 * HAIR, or they show as thin rings (around
        # Plasma's dots). A crack always lies against the band, so this adds no sliver.
        cracks = _thin(bands[k - 1].difference(fk), HAIR)
        fk = _tidy(unary_union([fk, cracks]).intersection(bands[k - 1]))
        if fk.is_empty:
            raise ValueError(f"{fig.name}: band {k} ({fig.bands[k]}) is empty; "
                             "remove it from bands or map some colour to it")
        bands.append(fk)
    return bands


@cache
def layout(fig: Figure) -> Layout:
    fig.validate()
    regions, body = artwork(fig)
    if fig.ground > 0:  # a bar under everything within `ground` of the bottom
        x0, y0, x1, _ = body.bounds
        gx0, _, gx1, _ = body.intersection(box(x0, y0, x1, y0 + fig.ground)).bounds
        body = _with_bar(body, gx0, gx1, y0, y0 + fig.ground)
    cut, foot = _foot(fig, body)
    y_cut = body.bounds[1] + cut

    def shift(g: BaseGeometry) -> BaseGeometry:
        return affinity.translate(g, 0, -y_cut)

    above = box(-1e4, y_cut, 1e4, 1e4)
    body = shift(body.intersection(above))
    regions = {f: shift(g.intersection(above)) for f, g in regions.items()}
    bands = colour_bands(fig, body, regions)
    # stand steady: a post (body colour, band 0 only) when the centre of mass lies
    # beside the foot. It changes no colour band, so the bands need no second pass.
    com = centre_x(bands, band_z(fig))
    post = _post(fig, body, foot, com) if fig.support else None
    if post is not None:
        body = _with_bar(body, post[0], post[1], 0.0, post[2])
        bands[0] = _with_bar(bands[0], post[0], post[1], 0.0, post[2])
        foot = (min(foot[0], post[0]), max(foot[1], post[1]))
        com = centre_x(bands, band_z(fig))
    # the tenon reaches 0.05 mm into the body, so the two always fuse into one solid
    tenon = box(foot[0], -fig.tenon_h, foot[1], 0.05)
    # _tidy, not _clean: simplifying would move band 0's edge by up to SIMPLIFY, more than
    # band 1's INSET, where band 1 runs along it
    bands[0] = _tidy(unary_union([bands[0], tenon]))
    x0, y0, x1, y1 = body.bounds
    return Layout(regions, body, tenon, bands, foot, cut, (x1 - x0, y1 - y0), com, post)


def band_z(fig: Figure) -> list[tuple[float, float]]:
    """(z0, z1) of every band in the print pose."""
    z = [(0.0, fig.base_t)]
    for _ in fig.bands[1:]:
        z.append((z[-1][1], round(z[-1][1] + fig.band_t, 6)))
    return z


def colour_changes(fig: Figure) -> list[tuple[float, str]]:
    """The M600s: (print_z of the first layer of the band, new filament)."""
    return [(P.layer_top(z0), f) for (z0, _), f in zip(band_z(fig)[1:], fig.bands[1:])]


def thickness(fig: Figure) -> float:
    return band_z(fig)[-1][1]


def _wire(coords) -> Wire | None:
    """A closed polygon wire, without the repeated points OCCT cannot join (on the GRID,
    two different points are at least GRID apart)."""
    pts = []
    for x, y in list(coords)[:-1]:
        if not pts or math.dist((x, y), pts[-1]) > GRID / 2:
            pts.append((x, y))
    while len(pts) > 1 and math.dist(pts[0], pts[-1]) <= GRID / 2:
        pts.pop()
    if len(pts) < 3 or Polygon(pts).area < 1e-4:
        return None
    return Wire.make_polygon([(x, y, 0) for x, y in pts], close=True)


def _faces(geom: BaseGeometry) -> list[Face]:
    """The faces of a footprint, with every corner on the GRID: all the solids of a part
    share it, whatever changed a band last (the tenon, the post, the hanging tab)."""
    faces = []
    for p in polygons(shapely.set_precision(geom, GRID)):
        outer = _wire(p.exterior.coords)
        if outer is None:
            continue
        holes = [w for w in (_wire(h.coords) for h in p.interiors) if w is not None]
        faces.append(Face(outer, holes))
    return faces


def inset(band: BaseGeometry, k: int) -> BaseGeometry:
    """The footprint of band k's solid: k * INSET inside the band's edge (see INSET)."""
    return band.buffer(-k * INSET, join_style="mitre") if k else band


def slab(geom: BaseGeometry, z0: float, z1: float) -> Part:
    """A footprint extruded from z0 to z1: one solid per polygon, not joined.

    The polygons of a band never overlap, so they need no boolean here: `fuse` joins them
    with the bands in one go. (Joining them one by one took 90 s for Katie's 150 pieces.)
    """
    # a clockwise ring has a downward normal: always give the direction (halloween gotcha)
    solids = [Pos(0, 0, z0) * extrude(f, z1 - z0, dir=(0, 0, 1)) for f in _faces(geom)]
    return solids[0] if len(solids) == 1 else Part(solids)


@cache
def band_parts(fig: Figure) -> tuple[Part, ...]:
    """One solid per band, in the print pose (lying, front face up)."""
    lay = layout(fig)
    return tuple(slab(inset(g, k), z0, z1)
                 for k, (g, (z0, z1)) in enumerate(zip(lay.bands, band_z(fig))))


def fuse(parts) -> Part:
    """One solid from stacked parts, in a single boolean (faster than one per part). The
    parts may be cached: they are not changed."""
    part = Pos() * parts[0]  # a copy: clean() works in place, and parts[0] may be cached
    # `+` with a list keeps the result a Part (fuse() would return a bare Solid, whose `&`
    # gives None instead of an empty part)
    return (part + list(parts[1:])).clean()


@cache
def make_figure(fig: Figure) -> Part:
    """The whole standee in the print pose: front face up, the tenon towards -y."""
    return fuse(band_parts(fig))


def standing(part: Part) -> Part:
    """Print pose -> standing on the pedestal: the front faces -y, the foot is at z = 0."""
    return Rot(90, 0, 0) * part


def coloured(fig: Figure, stand: bool = True) -> list[tuple[Part, str]]:
    """(band solid, filament) pairs: what each band looks like once printed."""
    parts = band_parts(fig)
    return [(standing(p) if stand else p, f) for p, f in zip(parts, fig.bands)]


def is_nested(lay: Layout) -> bool:
    """Every band rests on the band below it (no part of a band hangs in the air)."""
    return all(lay.bands[k].difference(lay.bands[k - 1]).area < 1e-3
               for k in range(1, len(lay.bands)))
