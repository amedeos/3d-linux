"""The 2D side: SVG reading, colour mapping, bands, foot, tenon and slot."""

import math
from dataclasses import replace

import numpy as np
import pytest
import shapely
from conftest import KINDS, layout_of, view_of
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from linux3d import params as P
from linux3d import pedestal, relief, svg
from linux3d.figures import DROP, FIGURES, Figure, figure, parse_value

FIGS = list(FIGURES.values())
IDS = list(FIGURES)


def square(x0, y0, size, clockwise=False):
    pts = [(x0, y0), (x0 + size, y0), (x0 + size, y0 + size), (x0, y0 + size)]
    return np.array(pts[::-1] if clockwise else pts, dtype=float)


@pytest.mark.parametrize("rule, inner_cw, hole", [("evenodd", False, True),
                                                  ("nonzero", False, False),
                                                  ("nonzero", True, True)])
def test_fill_rules(rule, inner_cw, hole):
    area = svg.filled_area([square(0, 0, 10), square(3, 3, 4, clockwise=inner_cw)], rule)
    assert area.area == pytest.approx(100 - 16 if hole else 100)


@pytest.mark.parametrize("fig", FIGS, ids=IDS)
def test_colour_map_matches_the_drawing(fig):
    """Every key of the colour map names a real shape or colour (no silent typos)."""
    shapes = relief._shapes(fig.svg_path)
    keys = {s.key for s in shapes} | {s.colour for s in shapes}
    assert [k for k, _ in fig.colours if k not in keys] == []


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("fig", FIGS, ids=IDS)
def test_every_band_shows(fig, kind):
    lay = layout_of(kind, fig)
    assert len(lay.bands) == len(fig.bands)
    assert all(b.area > 20 for b in lay.bands)
    assert set(lay.regions) <= set(fig.bands)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("fig", FIGS, ids=IDS)
def test_scale_is_uniform(fig, kind):
    """The drawing keeps its proportions (Gentoo's logo guidelines forbid distortion)."""
    fig = view_of(kind, fig)
    cmap = fig.colour_map()
    kept = [s for s in relief._shapes(fig.svg_path)
            if cmap.get(s.key, cmap.get(s.colour)) != DROP
            and (s.key in cmap or s.colour in cmap or s.opacity >= fig.min_opacity)]
    x0, y0, x1, y1 = unary_union([s.geom for s in svg.visible(kept)]).bounds
    art = unary_union(list(relief.drawing(fig).values()))
    ax0, ay0, ax1, ay1 = art.bounds
    # (the regions are simplified by 0.01 mm, so allow a little)
    assert ay1 - ay0 == pytest.approx(fig.height, abs=0.05)
    assert (ax1 - ax0) / (ay1 - ay0) == pytest.approx((x1 - x0) / (y1 - y0), rel=1e-3)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("fig", FIGS, ids=IDS)
def test_bands_are_nested(fig, kind):
    assert relief.is_nested(layout_of(kind, fig))


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("fig", FIGS + [figure("konqi", height=145.0, ornament_h=145.0)],
                         ids=IDS + ["konqi_145mm"])
def test_bands_are_valid_geometry(fig, kind):
    """At 145 mm, GEOS returned a buffer with crossed rings for Konqi, and the next boolean
    failed: opening() repairs it."""
    assert all(band.is_valid for band in layout_of(kind, fig).bands)


@pytest.mark.parametrize("fig", FIGS, ids=IDS)
def test_foot_and_tenon(fig):
    lay = relief.layout(fig)
    assert lay.foot[1] - lay.foot[0] >= min(fig.min_foot, 8.0)
    assert lay.cut <= fig.max_cut * fig.height
    # the tenon hangs below the foot and joins the body all along the flat contact
    joint = lay.tenon.intersection(lay.body).area / 0.05  # the tenon reaches 0.05 mm up
    assert joint >= 0.9 * min(fig.min_foot, lay.foot[1] - lay.foot[0])
    assert lay.bands[0].bounds[1] == pytest.approx(-fig.tenon_h)


@pytest.mark.parametrize("name", ["gentoo_logo", "kde_logo"])
def test_the_foot_does_not_cut_into_a_logo(name):
    """Gentoo's guidelines forbid changing the logo: the flat foot cuts only the margin."""
    fig = FIGURES[name]
    assert relief.layout(fig).cut <= fig.margin + 0.05


@pytest.mark.parametrize("fig", FIGS, ids=IDS)
def test_tenon_fits_the_slot(fig):
    lay, s = relief.layout(fig), pedestal.size(fig)
    x0, x1, y0, y1 = s.slot
    assert x1 - x0 == pytest.approx(lay.foot[1] - lay.foot[0] + 2 * P.CLR_SLOT)
    assert y1 - y0 == pytest.approx(fig.base_t + 2 * P.CLR_SLOT)
    assert fig.tenon_h + P.SLOT_FLOOR_GAP <= s.slot_depth < fig.pedestal_h


@pytest.mark.parametrize("fig", FIGS, ids=IDS)
def test_standing_figure_does_not_collide_with_its_pedestal(fig):
    standing = relief.standing(relief.make_figure(fig))
    assert (standing & pedestal.make_pedestal(fig)).volume < 1e-3


def test_gentoo_eye_stays_violet():
    lay = relief.layout(FIGURES["gentoo_logo"])
    holes = [h for p in relief.polygons(lay.bands[1]) for h in p.interiors]
    assert len(holes) == 1  # the eye: a violet pit in the white face


def test_larry_head_is_white():
    lay = relief.layout(FIGURES["larry"])
    x0, y0, x1, y1 = lay.body.bounds
    head = Point(x0 + 0.66 * (x1 - x0), y0 + 0.65 * (y1 - y0))  # the forehead
    assert lay.bands[1].contains(head)


RING = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
<path d="M10 10 H90 V90 H10 Z M30 30 V70 H70 V30 Z" fill="#000" fill-rule="evenodd"/>
<circle cx="50" cy="50" r="8" fill="#fff"/></svg>"""


def test_background_fills_enclosed_holes(tmp_path):
    """A drawing that relies on white paper inside a frame: background paints the hole."""
    path = tmp_path / "ring.svg"
    path.write_text(RING, encoding="utf-8")
    fig = Figure(name="ring", title="", svg=str(path), bands=("black", "white"), height=50.0)
    with pytest.raises(ValueError, match="falls apart"):  # the dot floats in the hole
        relief.layout(fig)
    lay = relief.layout(replace(fig, background="white"))
    paper = Point(0, lay.body.bounds[3] / 2 + 6)  # inside the frame, beside the dot
    assert lay.bands[0].contains(paper) and lay.bands[1].contains(paper)


def test_colour_changes_follow_the_bands():
    fig = FIGURES["konqi"]
    changes = relief.colour_changes(fig)
    assert [c for _, c in changes] == list(fig.bands[1:])
    assert [z for z, _ in changes] == pytest.approx([2.6, 3.4, 4.2, 5.0])


def test_overrides_and_validation():
    fig = figure("gentoo_logo", height=60.0)
    lay = relief.layout(fig)
    assert lay.size[1] == pytest.approx(60 + 2 * fig.margin - lay.cut, abs=0.01)
    with pytest.raises(ValueError, match="unknown filament"):
        figure("gentoo_logo", bands=("violet", "pink"))
    with pytest.raises(ValueError, match="falls apart"):  # the dots are not joined
        relief.layout(figure("plasma_logo", backing="outline", margin=1.0))
    assert parse_value(fig, "bands", "black, white") == ("black", "white")
    assert parse_value(fig, "height", "120") == 120.0
    assert parse_value(fig, "text_colour", "none") is None
    colours = parse_value(fig, "colours", "path919=violet, #b8b8b8=drop")
    assert colours == (("path919", "violet"), ("#b8b8b8", DROP))
    assert figure("gentoo_logo", colours=colours).colour_map()["path919"] == "violet"
    with pytest.raises(ValueError):
        parse_value(fig, "colours", "path919")


# --- fixes from the code review --------------------------------------------------------


def test_circle_backing_is_round():
    """The Plasma disc is a real circle, not shapely's 32-gon (9 mm flats)."""
    fig = FIGURES["plasma_logo"]
    lay = relief.layout(fig)
    art = unary_union(list(relief.drawing(fig).values()))
    radius = shapely.minimum_bounding_radius(art) + fig.margin
    pts = np.array(lay.body.exterior.coords)
    upper = pts[pts[:, 1] > 1.0]  # above the flat foot
    edges = np.linalg.norm(np.diff(upper, axis=0), axis=1)
    edges = edges[edges < 10]  # skip the jump across the foot
    sagitta = radius - np.sqrt(radius**2 - (edges.max() / 2) ** 2)
    assert sagitta < 0.02


def test_foot_falls_back_to_the_widest_contact():
    """If min_foot is never reached, keep the widest chord, within max_cut."""
    fig = figure("gentoo_logo", min_foot=1000.0)
    # widest at the very bottom, narrower above (an ankle)
    body = Polygon([(-20, 0), (20, 0), (5, 3), (5, 30), (-5, 30), (-5, 3)])
    cut, (x0, x1) = relief._foot(fig, body)
    assert cut <= fig.max_cut * fig.height
    assert cut < 0.1 and x1 - x0 > 39


def test_foot_never_cuts_deeper_than_max_cut():
    fig = figure("gentoo_logo", min_foot=1000.0, max_cut=0.05)
    body = Polygon([(-5, 0), (5, 0), (20, 30), (-20, 30)])  # wider all the way up
    cut, _ = relief._foot(fig, body)
    assert cut <= 0.05 * fig.height + 1e-9


def test_single_band_figure_does_not_change_the_cached_band():
    """clean() works in place: make_figure must not hand out or alter a cached part."""
    fig = figure("kde_logo", bands=("blue",), text_colour=None)
    band = relief.band_parts(fig)[0]
    faces = len(band.faces())
    part = relief.make_figure(fig)
    assert part is not band and len(relief.band_parts(fig)[0].faces()) == faces


@pytest.mark.parametrize("key, value", [("band_t", 0.7), ("base_t", 2.5),
                                        ("pedestal_h", 13.9), ("text_h", 0.5),
                                        ("ornament_t", 1.1)])
def test_off_grid_thickness_is_refused(key, value):
    with pytest.raises(ValueError, match="layers"):
        figure("konqi", **{key: value})


@pytest.mark.parametrize("changes", [{"bands": ()}, {"height": 0.0}, {"margin": -1.0},
                                     {"ornament_h": 0.0}, {"hole_d": -1.0}])
def test_bad_sizes_are_refused(changes):
    with pytest.raises(ValueError):
        figure("larry", **changes)


def test_slot_deeper_than_the_pedestal_is_refused_early():
    with pytest.raises(ValueError, match="pedestal_h at least 10.4"):
        figure("kde_logo", pedestal_h=10.0)


def test_pedestal_keeps_a_wall_in_front_of_the_slot():
    """Without lettering, the slot must not break through the front."""
    s = pedestal.size(figure("larry", title=""))
    assert s.slot[2] - s.y0 >= pedestal.SIDE_WALL + pedestal.CHAMFER - 1e-9


def test_too_small_pedestal_depth_is_refused():
    with pytest.raises(ValueError, match="use at least 17.8 mm"):
        pedestal.size(figure("larry", title="", pedestal_d=4.0))


def test_explicit_pedestal_depth_is_honoured():
    s = pedestal.size(figure("konqi", pedestal_d=60.0))
    assert s.y1 - s.y0 == pytest.approx(60.0)
    assert s.y1 == pytest.approx(pedestal.BACK_SHARE * 60.0)  # figure 45 % from the back


def test_small_figure_keeps_room_for_its_lettering():
    """The automatic depth grows for the lettering instead of failing (it used to fail
    for a 50 mm Plasma with thicker bands)."""
    fig = figure("plasma_logo", height=50.0, band_t=1.2)
    s = pedestal.size(fig)
    room = (-relief.thickness(fig) - pedestal.TEXT_GAP) - (s.y0 + pedestal.CHAMFER
                                                           + pedestal.TEXT_GAP)
    assert room >= pedestal.TEXT_ROOM - 1e-9
    assert pedestal.lettering(fig, s) is not None


@pytest.mark.parametrize("fig", FIGS, ids=IDS)
def test_plinth_grows_upwards_from_the_bottom(fig):
    """Both extrusions go up (dir given), so the plinth spans exactly -h .. 0."""
    bb = pedestal._plinth(pedestal.size(fig)).bounding_box()
    assert bb.min.Z == pytest.approx(-fig.pedestal_h) and bb.max.Z == pytest.approx(0.0)


# --- stability --------------------------------------------------------------------------
HEIGHTS = (60.0, 100.0, 150.0)
SUPPORTED = [n for n, f in FIGURES.items() if f.support]
# grams per cm3 of model, from PrusaSlicer (PETG, 15 % infill): the thin standees are
# almost solid, the pedestals are mostly infill
STANDEE_DENSITY, PEDESTAL_DENSITY = 0.92, 0.43


def contacts(lay) -> list[tuple[float, float]]:
    """Where the standee touches the pedestal's top face."""
    return relief.chord(lay.bands[0], 0.06)  # just above the tenon (it reaches 0.05)


@pytest.mark.parametrize("height", HEIGHTS)
@pytest.mark.parametrize("name", SUPPORTED)
def test_centre_of_mass_lies_over_the_support_at_any_height(name, height):
    """With `support`, the centre of mass lies 3 mm inside the support at every size:
    the post is placed from the centre of mass, not from fixed millimetres."""
    lay = relief.layout(figure(name, height=height))
    assert lay.foot[0] + relief.SUPPORT_MARGIN - 1e-6 <= lay.centre_x
    assert lay.centre_x <= lay.foot[1] - relief.SUPPORT_MARGIN + 1e-6
    # the printed contacts really surround the centre of mass (a round bottom makes them
    # a little wider than the cut, never narrower)
    touch = contacts(lay)
    assert touch[0][0] <= lay.centre_x - relief.SUPPORT_MARGIN
    assert touch[-1][1] >= lay.centre_x + relief.SUPPORT_MARGIN
    assert lay.foot[0] - 1.5 < touch[0][0] and touch[-1][1] < lay.foot[1] + 1.5


@pytest.mark.parametrize("name", SUPPORTED)
def test_centre_of_mass_of_the_solid_lies_over_the_support(name):
    """The same check on the real solid (with the tenon), at the default size."""
    fig = FIGURES[name]
    lay = relief.layout(fig)
    x = relief.standing(relief.make_figure(fig)).center().X
    assert lay.foot[0] + 2.5 < x < lay.foot[1] - 2.5


@pytest.mark.parametrize("height", (80.0, 120.0, 150.0))
def test_konqi_stands_on_both_feet(height):
    """Konqi stands on one foot, beside its centre of mass: a post under the raised foot
    gives a second support, and the tenon reaches under both."""
    lay = relief.layout(figure("konqi", height=height))
    assert lay.post is not None
    assert len(contacts(lay)) == 2
    alone = relief.layout(figure("konqi", height=height, support=False))
    assert alone.beside > 0 and alone.post is None


@pytest.mark.parametrize("name", ["larry", "kde_logo", "plasma_logo"])
def test_balanced_figures_get_no_post(name):
    assert relief.layout(FIGURES[name]).post is None


def test_gentoo_logo_is_left_untouched_and_leans_a_little():
    """A post would change the logo's outline: the "g" leans in the slot instead."""
    fig = FIGURES["gentoo_logo"]
    lay = relief.layout(fig)
    assert not fig.support and lay.post is None and lay.beside > 0
    assert relief.lean_limit(fig) < 0.75  # degrees: about 1 mm at the top
    assert relief.layout(replace(fig, support=True)).post is not None  # it would need one


BOOT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 60">
<path d="M0,60 L10,60 L10,20 L48,20 L50,55 L52,20 L60,20 L60,0 L0,0 Z" fill="#000"/></svg>"""
FLAG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 60">
<path d="M0,60 L4,60 L4,25 L60,25 L60,0 L0,0 Z" fill="#000"/></svg>"""


def _shape(tmp_path, text: str, **changes) -> Figure:
    path = tmp_path / "shape.svg"
    path.write_text(text, encoding="utf-8")
    return Figure(name="shape", title="", svg=str(path), bands=("black",), height=60.0,
                  min_foot=5.0, **changes)


def test_post_under_a_point_has_a_minimum_width(tmp_path):
    """The lowest part beyond the centre of mass is a spike tip: the post under it is
    still MIN_POST wide, and it is printed (it stays in band 0)."""
    lay = relief.layout(_shape(tmp_path, BOOT))
    x0, x1, _ = lay.post
    assert x1 - x0 >= relief.MIN_POST - 1e-6
    touch = contacts(lay)
    assert len(touch) == 2 and touch[1][1] - touch[1][0] >= relief.MIN_POST - 0.1


def test_figure_that_cannot_be_supported_is_refused(tmp_path):
    """A flag on a pole: nothing beyond the centre of mass comes near the ground."""
    with pytest.raises(ValueError, match="support=False"):
        relief.layout(_shape(tmp_path, FLAG))
    lay = relief.layout(_shape(tmp_path, FLAG, support=False))
    assert lay.post is None and lay.beside > 0


@pytest.mark.parametrize("fig", FIGS + [figure("larry", height=60.0),
                                        figure("plasma_logo", height=150.0)],
                         ids=IDS + ["larry-60", "plasma_logo-150"])
def test_assembly_does_not_tip_easily(fig):
    """Figure and pedestal must tilt at least 25° in every direction before they fall."""
    st = relief.standing(relief.make_figure(fig))
    ped = pedestal.make_pedestal(fig)
    gf, gp = st.volume * STANDEE_DENSITY, ped.volume * PEDESTAL_DENSITY
    cf, cp = st.center(), ped.center()
    cx = (gf * cf.X + gp * cp.X) / (gf + gp)
    cy = (gf * cf.Y + gp * cp.Y) / (gf + gp)
    cz = (gf * cf.Z + gp * cp.Z) / (gf + gp) + fig.pedestal_h
    s = pedestal.size(fig)
    for side, d in (("left", cx - s.x0), ("right", s.x1 - cx), ("front", cy - s.y0),
                    ("back", s.y1 - cy)):
        assert math.degrees(math.atan2(d, cz)) >= 25, side
