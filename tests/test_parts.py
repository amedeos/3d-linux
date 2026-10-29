import numpy as np
import pytest
from scipy.spatial import cKDTree

from linux3d import pedestal, relief
from linux3d.coupon import coupon_parts
from linux3d.export import check, mesh_problems
from linux3d.figures import FIGURES

NAMES = ([f"{n}_{kind}" for n in FIGURES
          for kind in ("standee", "pedestal", "ornament_front", "ornament_back")]
         + list(coupon_parts()))


@pytest.mark.parametrize("name", NAMES)
def test_part_is_printable(parts, name):
    assert check(parts[name]) == []


@pytest.mark.parametrize("name", NAMES)
def test_stl_mesh_is_watertight(parts, name):
    assert mesh_problems(parts[name]) == []


@pytest.mark.parametrize("name", [n for n in NAMES if n.endswith(("_standee", "_front", "_back"))])
def test_no_corners_a_fraction_of_a_micron_apart(parts, name):
    """Two corners closer than half the GRID make an edge that short, and zero-area
    triangles in the STL. The GRID and the INSET of the bands prevent them."""
    corners = np.array([tuple(v) for v in parts[name].vertices()])
    assert not cKDTree(corners).query_pairs(relief.GRID / 2)


@pytest.mark.parametrize("name", list(FIGURES))
def test_volumes_are_sane(parts, name):
    # a boolean that fails silently can drop half of a part without any error
    standee = parts[f"{name}_standee"].volume / 1000
    assert 8 < standee < 40
    # the pedestal is nearly the full block that pedestal.size() plans (the slot and the
    # chamfer take a few per cent, the lettering adds a little), whatever its size
    s = pedestal.size(FIGURES[name])
    planned = (s.x1 - s.x0) * (s.y1 - s.y0) * s.h
    assert 0.94 < parts[f"{name}_pedestal"].volume / planned < 1.0
    halves = [parts[f"{name}_ornament_{side}"].volume / 1000 for side in ("front", "back")]
    assert 2 < halves[0] < 15 and halves[1] == pytest.approx(halves[0], rel=1e-3)
