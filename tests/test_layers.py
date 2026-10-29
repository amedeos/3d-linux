"""Printability on a Prusa MK4: 0.4 mm nozzle, PrusaSlicer "0.20mm STRUCTURAL" profile."""

import pytest
from build123d import GeomType
from conftest import KINDS, layout_of, view_of

from linux3d import params as P
from linux3d import pedestal, relief
from linux3d.coupon import coupon_parts
from linux3d.figures import FIGURES

FIGS = list(FIGURES.values())
IDS = list(FIGURES)
NAMES = ([f"{n}_{kind}" for n in FIGURES
          for kind in ("standee", "pedestal", "ornament_front", "ornament_back")]
         + list(coupon_parts()))


def off_grid_faces(part) -> list[float]:
    """Heights of flat horizontal faces that do not sit on a layer boundary."""
    heights = []
    for face in part.faces():
        if face.geom_type == GeomType.PLANE and abs(abs(face.normal_at().Z) - 1) < 1e-6:
            z = face.center().Z
            if not P.on_grid(z):
                heights.append(round(z, 3))
    return sorted(set(heights))


@pytest.mark.parametrize("name", NAMES)
def test_flat_faces_sit_on_layer_boundaries(parts, name):
    assert off_grid_faces(parts[name]) == []


def test_profile_assumptions():
    assert P.FIRST_LAYER == P.LAYER == 0.2
    assert P.LINE_W == 0.45 and P.NOZZLE == 0.4
    assert P.lines(1) == pytest.approx(P.LINE_W)
    assert P.layers(12) == pytest.approx(2.4)
    assert P.on_grid(P.BASE_T) and P.on_grid(P.BAND_T)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("fig", FIGS, ids=IDS)
def test_colour_changes_come_before_each_band(fig, kind):
    # every band starts on a layer boundary, and its M600 comes before its first layer
    view = view_of(kind, fig)
    for (z0, z1), (print_z, colour), name in zip(relief.band_z(view)[1:],
                                                 relief.colour_changes(view), fig.bands[1:]):
        assert P.on_grid(z0) and P.on_grid(z1)
        assert print_z == pytest.approx(z0 + P.LAYER) and colour == name
    change = pedestal.text_change(fig)
    if change and kind == "standee":
        assert P.on_grid(fig.pedestal_h) and change[0] == pytest.approx(fig.pedestal_h + P.LAYER)


def test_band_thickness():
    # at least 4 layers per colour band; the body is thick enough for a stiff standee
    assert P.BAND_T >= 4 * P.LAYER and P.BASE_T >= 10 * P.LAYER


def _thin_fraction(geom, min_width: float, px_per_mm: float = 20.0) -> float:
    """Share of the area in parts thinner than `min_width` (morphological opening)."""
    import numpy as np
    from scipy import ndimage

    from linux3d.render import mask as raster

    if geom.is_empty:
        return 0.0
    m = np.array(raster(geom, geom.bounds, px_per_mm, pad=20), dtype=bool)
    if not m.any():
        return 0.0
    r = round(min_width / 2 * px_per_mm)
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    opened = ndimage.binary_opening(m, structure=xx**2 + yy**2 <= r * r)
    return 1 - opened.sum() / m.sum()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("fig", FIGS, ids=IDS)
def test_no_lone_slivers(fig, kind):
    """Every piece of a raised band survives the opening by a line: the 1.5 % area
    allowance of the stroke test cannot hide whole islands that are too thin to print."""
    lay = layout_of(kind, fig)
    for k, band in enumerate(lay.bands[1:], start=1):
        lone = [round(p.area, 3) for p in relief.polygons(band)
                if relief.opening(p, 0.95 * P.MIN_STROKE / 2).is_empty]
        assert lone == [], f"band {k} ({fig.bands[k]})"


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("fig", FIGS, ids=IDS)
def test_raised_strokes_are_printable(fig, kind):
    # Arachne drops walls thinner than min_bead_width (85 % of a line). Corners always lose
    # a little in the opening, so allow 1.5 % of the area.
    for k, band in enumerate(layout_of(kind, fig).bands[1:], start=1):
        assert _thin_fraction(band, P.MIN_STROKE) < 0.015, f"band {k} ({fig.bands[k]})"


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("fig", FIGS, ids=IDS)
def test_grooves_stay_open(fig, kind):
    """What shows of a lower colour between raised areas is at least one line wide."""
    lay = layout_of(kind, fig)
    for k in range(1, len(lay.bands)):
        lower = lay.bands[k - 1].difference(lay.bands[k])
        assert _thin_fraction(lower, P.MIN_GAP) < 0.03, f"under band {k} ({fig.bands[k]})"


@pytest.mark.parametrize("fig", FIGS, ids=IDS)
def test_lettering_strokes_are_printable(fig):
    text = pedestal.lettering(fig, pedestal.size(fig))
    face = max(text.faces(), key=lambda f: f.center().Z)  # the top of the letters
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    shapes = []
    for f in text.faces():
        if f.geom_type == GeomType.PLANE and f.center().Z == pytest.approx(face.center().Z):
            verts, tris = f.tessellate(0.01)
            shapes += [Polygon([(verts[i].X, verts[i].Y) for i in t]) for t in tris]
    assert _thin_fraction(unary_union(shapes), P.MIN_STROKE) < 0.015


def _layer_sections(part):
    """Cross-sections (shapely polygons) at the middle of every layer."""
    import numpy as np
    import trimesh

    verts, tris = part.tessellate(0.02, 0.2)
    mesh = trimesh.Trimesh([[v.X, v.Y, v.Z] for v in verts], tris)
    top = part.bounding_box().max.Z
    heights = np.arange(P.LAYER / 2, top, P.LAYER)
    paths = mesh.section_multiplane([0, 0, 0], [0, 0, 1], heights)
    return [list(p.polygons_full) if p is not None else [] for p in paths]


@pytest.mark.parametrize("name", NAMES)
def test_no_floating_islands(parts, name):
    """Every island of every layer must rest on the layer below (nothing starts in mid-air)."""
    from shapely.ops import unary_union

    layers = _layer_sections(parts[name])
    for k in range(1, len(layers)):
        below = unary_union(layers[k - 1]) if layers[k - 1] else None
        for poly in layers[k]:
            if poly.area < 0.05:  # tessellation crumbs
                continue
            assert below is not None and poly.intersection(below).area > 0.01, (
                f"island of {poly.area:.2f} mm2 at z={(k + 0.5) * P.LAYER:.1f}")
