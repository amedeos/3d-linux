"""Christmas tree ornaments: they hang upright, the tab and its hole (or the hole through
a shape of the drawing), and two halves that line up once glued."""

import math
import re

import pytest
from build123d import Box, Plane, Pos
from conftest import fig_id
from shapely.geometry import Point, box

from linux3d import ornament, relief
from linux3d import params as P
from linux3d.figures import FIGURES, Figure, figure

FIGS = list(FIGURES.values())
IDS = list(FIGURES)
TABBED = [f for f in FIGS if not f.hang_from]  # a tab with the hole on top
HUNG = [f for f in FIGS if f.hang_from]  # the hole goes through a shape (Znurt's antenna)


@pytest.mark.parametrize("height", (50.0, 70.0, 100.0))
@pytest.mark.parametrize("name", IDS)
def test_ornament_hangs_upright_at_any_size(name, height):
    """The hole lies straight above the centre of mass of the glued ornament: placed from
    the centre of mass, not from fixed millimetres."""
    lay = ornament.layout(figure(name, ornament_h=height))
    assert lay.tilt < ornament.MAX_TILT
    assert lay.hole[1] - lay.hole[2] > lay.centre[1]  # the hole is above it


@pytest.mark.parametrize("fig", FIGS, ids=IDS)
def test_glued_ornament_hangs_upright(fig):
    """The same check on the real solids: both halves, the back one turned over (x -> -x),
    sockets included."""
    front, back = ornament.make_half(fig), ornament.make_half(fig, back=True)
    (vf, cf), (vb, cb) = ((s.volume, s.center()) for s in (front, back))
    cx = (vf * cf.X - vb * cb.X) / (vf + vb)
    cy = (vf * cf.Y + vb * cb.Y) / (vf + vb)
    x, y, _ = ornament.layout(fig).hole
    assert math.degrees(math.atan2(abs(cx - x), y - cy)) < ornament.MAX_TILT
    # the bands' solids (the hanging preview's mark) give the same centre as the halves
    assert ornament.mass_centre(fig) == pytest.approx((cx, cy), abs=0.01)


@pytest.mark.parametrize("fig", TABBED, ids=fig_id)
def test_hole_is_ringed_by_the_tab_and_clear_of_the_drawing(fig):
    lay = ornament.layout(fig)
    x, y, r = lay.hole
    hole = Point(x, y).buffer(r)
    assert r == pytest.approx(fig.hole_d / 2)
    # a real hole (the cleanup simplifies its edge by up to SIMPLIFY)
    assert lay.bands[0].intersection(hole.buffer(-2 * relief.SIMPLIFY)).area < 1e-3
    ring = Point(x, y).buffer(r + ornament.RING_W - 0.05).difference(hole.buffer(0.05))
    assert ring.difference(lay.bands[0]).area < 1e-3  # a full ring of material around it
    assert hole.distance(lay.body) >= ornament.RING_W - 0.01  # the thread misses the drawing


@pytest.mark.parametrize("fig", TABBED, ids=fig_id)
def test_tab_changes_only_the_top_of_the_body(fig):
    """The tab is band 0 only, and it adds material only at the top of the outline: the
    drawing keeps its shape and colours (Gentoo's guidelines)."""
    lay = ornament.layout(fig)
    for band in lay.bands[1:]:
        assert band.difference(lay.body).area < 1e-3
    hair = 5 * relief.SIMPLIFY  # the cleanup moves edges by less than this
    added = lay.bands[0].difference(lay.body.buffer(hair))
    _, y, r = lay.hole
    assert added.bounds[1] >= y - 2 * (r + ornament.RING_W) - 0.01
    assert added.difference(lay.tab.buffer(hair)).area < 1e-3  # all it adds is the tab
    assert lay.body.buffer(-hair).difference(lay.bands[0]).area < 1e-3  # and it cuts nothing


@pytest.mark.parametrize("height", (30.0, 35.0, 40.0))
def test_znurt_hangs_from_its_antenna_at_the_sizes_it_prints(height):
    """Znurt fits the bed only up to about 40 mm (its halves lie side by side). At every
    size it can print, the hole has its wall and the ornament hangs upright."""
    fig = figure("znurt", ornament_h=height)
    lay = ornament.layout(fig)
    x, y, r = lay.hole
    assert lay.body.boundary.distance(Point(x, y)) - r >= ornament.RING_W - 1e-6
    assert lay.tilt < ornament.MAX_TILT


@pytest.mark.parametrize("fig", HUNG, ids=fig_id)
def test_hole_through_a_shape_is_ringed_by_its_eyelet(fig):
    """No tab: the hole goes through every band, inside the shape, and the shape's colour
    rings it with RING_W of wall (the eyelet reaches the edge of the body)."""
    lay = ornament.layout(fig)
    x, y, r = lay.hole
    hole = Point(x, y).buffer(r)
    assert lay.tab.is_empty and r == pytest.approx(fig.hole_d / 2)
    for band in lay.bands:  # a real hole, through every band
        assert band.intersection(hole.buffer(-2 * relief.SIMPLIFY)).area < 1e-3
    filament, shape = relief.shape_area(ornament.as_ornament(fig), fig.hang_from)
    assert shape.contains(Point(x, y))
    ring = Point(x, y).buffer(r + ornament.RING_W - 0.05).difference(hole.buffer(0.05))
    assert ring.difference(lay.bands[0]).area < 1e-3  # a full ring of material
    assert ring.difference(lay.bands[fig.bands.index(filament)]).area < 1e-3  # in colour


@pytest.mark.parametrize("fig", HUNG, ids=fig_id)
def test_hole_through_a_shape_adds_nothing_and_cuts_only_the_hole(fig):
    """The outline keeps its shape: band 0 is the body minus the hole."""
    lay = ornament.layout(fig)
    x, y, r = lay.hole
    hair = 5 * relief.SIMPLIFY
    for band in lay.bands:
        assert band.difference(lay.body.buffer(hair)).area < 1e-3
    cut = lay.body.buffer(-hair).difference(lay.bands[0])
    assert cut.difference(Point(x, y).buffer(r + hair)).area < 1e-3


def test_hole_moves_over_the_centre_of_mass_inside_the_shape():
    """Znurt's ball is 0.35 mm beside the centre of mass: the hole moves sideways within
    the ball, so the ornament hangs upright instead of 0.9° off."""
    fig = FIGURES["znurt"]
    lay = ornament.layout(fig)
    _, ball = relief.shape_area(ornament.as_ornament(fig), fig.hang_from)
    assert abs(lay.hole[0] - ball.centroid.x) > 0.2  # it moved
    assert abs(lay.hole[0] - lay.centre[0]) < 0.01  # to the centre of mass
    assert lay.hole[1] == pytest.approx(ball.centroid.y)  # sideways only


@pytest.mark.parametrize("changes, message", [
    ({"ornament_h": 25.0}, "leaves a wall of only"),  # too small for the 3 mm hole
    ({"hang_from": "path3866-4"}, "leaves a wall of only"),  # an eye: too small
    ({"hang_from": "path3007"}, "lies outside the shape"),  # the rim: a ring
    ({"hang_from": "path0"}, "is not a shape the figure keeps"),  # refused by validate()
    ({"hang_from": "path3813"}, "is not a shape the figure keeps"),  # the glow: shading
])
def test_hole_through_a_shape_that_cannot_hold_it_is_an_error(changes, message):
    with pytest.raises(ValueError, match=message):
        ornament.layout(figure("znurt", **changes))


@pytest.mark.parametrize("height", (27.9, 28.0))  # 28 mm: 0.4 um short of the wall
def test_wall_message_never_shows_equal_numbers(height):
    """Just below the wall it needs, the message must not read "2.08 (at least 2.08)"."""
    with pytest.raises(ValueError) as e:
        ornament.layout(figure("znurt", ornament_h=height))
    wall, least = (float(v) for v in re.findall(r"(\d+\.\d+) mm", str(e.value))[:1]
                   + re.findall(r"at least (\d+\.\d+)", str(e.value)))
    assert wall < least


def test_eyelet_takes_over_only_the_body_colour():
    """The eyelet recolours the backing and the drawing's parts in the body colour (the
    top of Znurt's violet antenna), never another colour of the drawing."""
    fig = FIGURES["znurt"]
    lay = ornament.layout(fig)
    drawn = relief.drawing(ornament.as_ornament(fig))  # mirrored back: the same frame
    for filament in ("white", "black"):
        assert lay.regions[filament].symmetric_difference(drawn[filament]).area < 1e-6
    assert lay.regions["orange"].area > drawn["orange"].area + 10  # the eyelet
    assert lay.regions["violet"].area < drawn["violet"].area  # the top of the antenna


def test_eyelet_of_a_lower_band_leaves_a_higher_colour_alone():
    """With the ball's orange as the body colour, the violet antenna keeps its colour:
    it runs into the ring around the hole, so the hole is refused, not recoloured."""
    with pytest.raises(ValueError, match="leaves a wall of only"):
        ornament.layout(figure("znurt", bands=("orange", "violet", "white", "black")))


# Drawings for hang_from on purpose: a square with orange balls on it. SYMMETRIC has one
# ball on the axis, a pair beside it and one below; LOPSIDED one ball at a top corner.
SYMMETRIC = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 110">
<rect x="0" y="30" width="60" height="60" fill="#1f6fd1"/>
<circle id="ball" cx="30" cy="22" r="8" fill="#f07318"/>
<circle id="ballL" cx="8" cy="22" r="8" fill="#f07318"/>
<circle id="ballR" cx="52" cy="22" r="8" fill="#f07318"/>
<circle id="drop" cx="30" cy="98" r="8" fill="#f07318"/></svg>"""
LOPSIDED = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 92">
<rect x="0" y="30" width="60" height="60" fill="#1f6fd1"/>
<circle id="ball" cx="52" cy="22" r="8" fill="#f07318"/></svg>"""


def _drawing(tmp_path, text: str, hang_from: str, bands=("blue", "orange")) -> Figure:
    path = tmp_path / "balls.svg"
    path.write_text(text, encoding="utf-8")
    return Figure(name="balls", title="", svg=str(path), bands=bands,
                  standee=False, ornament_h=60.0, hole_d=3.0, hang_from=hang_from)


def test_hole_through_a_shape_on_a_symmetric_outline_lies_on_the_axis(tmp_path):
    """The back half is a copy: the holes of the two halves only line up on the axis."""
    fig = _drawing(tmp_path, SYMMETRIC, "ball")
    lay = ornament.layout(fig)
    assert not lay.mirror_back and lay.hole[0] == 0.0
    front = ornament.make_half(fig)
    turned = ornament.make_half(fig, back=True).mirror(Plane.YZ)
    glued = Pos(0, 0, P.SOCKET_DEPTH) * Box(1e3, 1e3, 2 * P.SOCKET_DEPTH)
    f, t = front & glued, turned & glued
    assert (f & t).volume == pytest.approx(f.volume, rel=1e-4)


@pytest.mark.parametrize("ball, message", [
    ("ballR", "does not reach the axis of the symmetric outline"),
    ("drop", "does not lie above the centre"),  # below the centre of mass
])
def test_hole_that_would_not_hang_a_symmetric_ornament_is_an_error(tmp_path, ball, message):
    with pytest.raises(ValueError, match=message):
        ornament.layout(_drawing(tmp_path, SYMMETRIC, ball))


def test_hole_through_a_shape_with_no_drawing_in_the_body_colour(tmp_path):
    """Only the backing is in the body colour (like Plasma, Debian and Arch, which have no
    white in the drawing): the eyelet has no body region to take over, and that is fine."""
    orange = SYMMETRIC.replace('fill="#1f6fd1"', 'fill="#f07318"')
    lay = ornament.layout(_drawing(tmp_path, orange, "ball", bands=("white", "orange")))
    assert lay.hole[0] == 0.0


def test_hole_far_beside_the_centre_of_mass_is_an_error(tmp_path):
    """The ball at a corner: within its eyelet, the hole cannot get over the centre of
    mass, and the ornament would hang crooked."""
    with pytest.raises(ValueError, match="off upright"):
        ornament.layout(_drawing(tmp_path, LOPSIDED, "ball"))


def test_tab_that_does_not_settle_is_an_error(monkeypatch):
    """If the tab and the centre of mass never agree, layout() must not return a hole that
    is not the one it cut."""
    real, calls = relief.centre, []

    def drifting(bands, z):
        calls.append(None)
        x, y = real(bands, z)
        return x + 0.5 * len(calls), y

    monkeypatch.setattr(relief, "centre", drifting)
    with pytest.raises(ValueError, match="does not settle"):
        ornament.layout.__wrapped__(FIGURES["larry"])  # not the cached layout


def test_one_notch_makes_an_outline_asymmetric():
    """The largest gap counts: on average, a notch in a long edge is almost nothing."""
    square = box(-25, 0, 25, 50)
    assert ornament.is_symmetric(square)
    assert not ornament.is_symmetric(square.difference(box(24.7, 20, 25, 20.5)))


def test_back_half_is_a_copy_only_for_symmetric_outlines():
    """A copy of the front reads the right way round from behind, but turned over it only
    lies behind the front if the outline is symmetric."""
    mirror = {name: ornament.layout(fig).mirror_back for name, fig in FIGURES.items()}
    assert mirror == {"gentoo_logo": True, "larry": True, "kde_logo": False,
                      "plasma_logo": False, "konqi": True, "tux": True, "gnu": True,
                      "debian_logo": False, "arch_logo": True, "fedora_logo": True,
                      "katie": True, "znurt": True}
    for name in ("kde_logo", "plasma_logo", "debian_logo"):
        lay = ornament.layout(FIGURES[name])
        x0, _, x1, _ = lay.body.bounds
        assert lay.hole[0] == 0.0 and abs(x0 + x1) < 1e-6  # the axis is at x = 0
        assert ornament.is_symmetric(lay.body)


@pytest.mark.parametrize("fig", FIGS, ids=IDS)
def test_halves_line_up_once_glued(fig):
    """Turned over (x -> -x), the back half lies exactly behind the front: the outline,
    the hole and the dowel sockets. Checked on the solids, so a wrongly turned ring would
    show too."""
    front = ornament.make_half(fig)
    turned = ornament.make_half(fig, back=True).mirror(Plane.YZ)
    assert turned.volume == pytest.approx(front.volume, rel=1e-4)
    a, b = front.bounding_box(), turned.bounding_box()
    assert (a.min - b.min).length < 0.01 and (a.max - b.max).length < 0.01
    # the glued layers, sockets included, are the same solid
    glued = Pos(0, 0, P.SOCKET_DEPTH) * Box(1e3, 1e3, 2 * P.SOCKET_DEPTH)
    f, t = front & glued, turned & glued
    assert (f & t).volume == pytest.approx(f.volume, rel=1e-4)
    assert t.volume == pytest.approx(f.volume, rel=1e-4)


@pytest.mark.parametrize("fig", FIGS, ids=IDS)
def test_dowel_sockets_sit_inside_the_body_far_apart(fig):
    lay = ornament.layout(fig)
    (x0, y0), (x1, y1) = lay.sockets
    bx0, by0, bx1, by1 = lay.body.bounds  # the sockets lie in the body, not in the tab
    assert math.hypot(x1 - x0, y1 - y0) > 0.5 * max(bx1 - bx0, by1 - by0)
    for p in lay.sockets:
        assert Point(p).buffer(P.SOCKET_D / 2 + ornament.SOCKET_WALL - 0.01).within(lay.body)
    # blind holes: the glued face has them, the layer above the sockets does not
    half = ornament.make_half(fig)
    below = half & (Pos(0, 0, P.SOCKET_DEPTH / 2) * Box(1e3, 1e3, P.SOCKET_DEPTH))
    above = half & (Pos(0, 0, P.SOCKET_DEPTH + P.LAYER / 2) * Box(1e3, 1e3, P.LAYER))
    sockets = 2 * math.pi * (P.SOCKET_D / 2) ** 2 * P.SOCKET_DEPTH
    area = lay.bands[0].area
    assert below.volume == pytest.approx(area * P.SOCKET_DEPTH - sockets, rel=1e-3)
    assert above.volume == pytest.approx(area * P.LAYER, rel=1e-3)


def test_ornament_is_thin_and_light():
    """Two halves of 1.2 mm bodies: the glued core is as thick as a standee's body."""
    fig = FIGURES["konqi"]
    view = ornament.as_ornament(fig)
    assert 2 * view.base_t == pytest.approx(fig.base_t)
    assert relief.thickness(view) == pytest.approx(fig.ornament_t + 4 * fig.band_t)
    assert ornament.colour_changes(fig)[0][0] == pytest.approx(fig.ornament_t + P.LAYER)


def test_too_thin_body_for_the_sockets_is_refused():
    with pytest.raises(ValueError, match="dowel sockets; use at least 1.0"):
        figure("larry", ornament_t=0.8)
