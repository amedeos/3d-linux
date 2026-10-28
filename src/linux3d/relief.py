"""From an SVG drawing to a printable standee: colour bands, foot and tenon.

All the 2D work happens in shapely (fast and robust): colour regions, the body, the cut
that gives the figure a flat foot, the tenon, and the cleanup that makes every band
printable with 0.45 mm lines. build123d only extrudes the finished bands.

2D frame ("standing"): x is centred on the drawing, y points up, and the foot is cut at
y = 0. The tenon hangs below y = 0, inside the pedestal.

Print pose (`make_figure`): the same x and y on the bed, the front face up (+z).
"""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

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


@dataclass(frozen=True)
class Layout:
    """The figure in 2D (standing frame, mm)."""

    regions: dict[str, BaseGeometry]  # filament -> visible area of the drawing
    body: BaseGeometry  # band 0 above the foot (drawing + backing, cut flat)
    tenon: Polygon  # below y = 0
    bands: list[BaseGeometry]  # printable footprint of every band; bands[0] has the tenon
    foot: tuple[float, float]  # x range of the flat contact at y = 0
    cut: float  # how much of the drawing's bottom was cut off for the foot (mm)
    size: tuple[float, float]  # width and height of the body


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
    """Remove every part thinner than 2 r (morphological opening)."""
    if geom.is_empty:
        return geom
    return geom.buffer(-r, join_style="round").buffer(r, join_style="round")


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


def _foot(fig: Figure, body: Polygon) -> tuple[float, tuple[float, float]]:
    """Height of the cut that gives a flat contact of at least min_foot, and its x range.

    The first cut that reaches min_foot wins. If none does within max_cut of the height,
    the cut with the widest contact wins.
    """
    x0, y0, x1, _ = body.bounds
    best = (0.0, (0.0, 0.0), 0.0)
    # steps of 0.1 mm (the foot does not have to be on any grid); start just above the
    # bottom, so that a flat bottom tilted by the simplification still counts as flat
    limit = fig.max_cut * fig.height
    c = 2 * SIMPLIFY
    while c <= limit + 1e-9:
        chord = body.intersection(LineString([(x0 - 1, y0 + c), (x1 + 1, y0 + c)]))
        if not chord.is_empty and chord.length > best[2]:
            cb = chord.bounds
            best = (c, (cb[0], cb[2]), chord.length)
            if chord.length >= fig.min_foot:
                break
        c = round(c + 0.1, 6)
    if best[2] <= 0:
        raise ValueError(f"{fig.name}: no flat foot found")
    return best[0], best[1]


def _thin(geom: BaseGeometry, r: float) -> BaseGeometry:
    """The parts of a geometry narrower than 2 r."""
    return geom.difference(opening(geom, r)) if not geom.is_empty else geom


@cache
def layout(fig: Figure) -> Layout:
    fig.validate()
    regions = drawing(fig)
    art = unary_union(list(regions.values()))
    if fig.background:
        filled = unary_union([Polygon(p.exterior) for p in polygons(art)])
        holes = filled.difference(art)
        if not holes.is_empty:
            regions[fig.background] = unary_union([regions.get(fig.background, Polygon()),
                                                   holes])
        art = filled
    body = _backing(fig, art)
    if fig.ground > 0:  # a bar under everything within `ground` of the bottom
        x0, y0, x1, y1 = body.bounds
        gx0, _, gx1, _ = body.intersection(box(x0, y0, x1, y0 + fig.ground)).bounds
        body = unary_union([body, box(gx0, y0, gx1, y0 + fig.ground)])
    cut, foot = _foot(fig, body)
    y_cut = body.bounds[1] + cut

    def shift(g: BaseGeometry) -> BaseGeometry:
        return affinity.translate(g, 0, -y_cut)

    above = box(-1e4, y_cut, 1e4, 1e4)
    body = shift(body.intersection(above))
    regions = {f: shift(g.intersection(above)) for f, g in regions.items()}
    # the tenon reaches 0.05 mm into the body, so the two always fuse into one solid
    tenon = box(foot[0], -fig.tenon_h, foot[1], 0.05)

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
    bands[0] = _clean(unary_union([bands[0], tenon]))
    x0, y0, x1, y1 = body.bounds
    return Layout(regions, body, tenon, bands, foot, cut, (x1 - x0, y1 - y0))


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
    """A closed polygon wire, without the near-duplicate points OCCT cannot join."""
    pts = []
    for x, y in list(coords)[:-1]:
        if not pts or abs(x - pts[-1][0]) + abs(y - pts[-1][1]) > 1e-3:
            pts.append((x, y))
    while len(pts) > 1 and abs(pts[0][0] - pts[-1][0]) + abs(pts[0][1] - pts[-1][1]) <= 1e-3:
        pts.pop()
    if len(pts) < 3 or Polygon(pts).area < 1e-4:
        return None
    return Wire.make_polygon([(x, y, 0) for x, y in pts], close=True)


def _faces(geom: BaseGeometry) -> list[Face]:
    faces = []
    for p in polygons(geom):
        outer = _wire(p.exterior.coords)
        if outer is None:
            continue
        holes = [w for w in (_wire(h.coords) for h in p.interiors) if w is not None]
        faces.append(Face(outer, holes))
    return faces


def slab(geom: BaseGeometry, z0: float, z1: float) -> Part:
    """A footprint extruded from z0 to z1."""
    # a clockwise ring has a downward normal: always give the direction (halloween gotcha)
    solids = [Pos(0, 0, z0) * extrude(f, z1 - z0, dir=(0, 0, 1)) for f in _faces(geom)]
    part = solids[0]
    for s in solids[1:]:
        part = part + s
    return part


@cache
def band_parts(fig: Figure) -> tuple[Part, ...]:
    """One solid per band, in the print pose (lying, front face up)."""
    lay = layout(fig)
    return tuple(slab(g, z0, z1) for g, (z0, z1) in zip(lay.bands, band_z(fig)))


@cache
def make_figure(fig: Figure) -> Part:
    """The whole standee in the print pose: front face up, the tenon towards -y."""
    parts = band_parts(fig)
    part = Pos() * parts[0]  # a copy: clean() works in place, and parts[0] is cached
    for p in parts[1:]:
        part = part + p
    return part.clean()


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
