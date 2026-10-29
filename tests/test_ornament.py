"""Christmas tree ornaments: they hang upright, the tab and its hole, and two halves that
line up once glued."""

import math

import pytest
from build123d import Box, Plane, Pos
from shapely.geometry import Point, box

from linux3d import ornament, relief
from linux3d import params as P
from linux3d.figures import FIGURES, figure

FIGS = list(FIGURES.values())
IDS = list(FIGURES)


@pytest.mark.parametrize("height", (50.0, 70.0, 100.0))
@pytest.mark.parametrize("name", IDS)
def test_ornament_hangs_upright_at_any_size(name, height):
    """The hole lies straight above the centre of mass of the glued ornament: placed from
    the centre of mass, not from fixed millimetres."""
    lay = ornament.layout(figure(name, ornament_h=height))
    assert lay.tilt < 1.0
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
    assert math.degrees(math.atan2(abs(cx - x), y - cy)) < 1.0


@pytest.mark.parametrize("fig", FIGS, ids=IDS)
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


@pytest.mark.parametrize("fig", FIGS, ids=IDS)
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
                      "katie": True}
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
    assert math.hypot(x1 - x0, y1 - y0) > 0.5 * max(lay.size)
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
