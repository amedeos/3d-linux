import pytest

from linux3d.coupon import coupon_parts
from linux3d.export import check, mesh_problems
from linux3d.figures import FIGURES

NAMES = [f"{n}_{kind}" for n in FIGURES for kind in ("standee", "pedestal")] + list(coupon_parts())


@pytest.mark.parametrize("name", NAMES)
def test_part_is_printable(parts, name):
    assert check(parts[name]) == []


@pytest.mark.parametrize("name", NAMES)
def test_stl_mesh_is_watertight(parts, name):
    assert mesh_problems(parts[name]) == []


@pytest.mark.parametrize("name", list(FIGURES))
def test_volumes_are_sane(parts, name):
    # a boolean that fails silently can drop half of a part without any error
    standee = parts[f"{name}_standee"].volume / 1000
    pedestal = parts[f"{name}_pedestal"].volume / 1000
    assert 8 < standee < 40 and 30 < pedestal < 80
