"""Shared fixtures: every figure is built once per test session (building takes ~30 s)."""

import pytest

from linux3d import ornament, relief
from linux3d.coupon import coupon_parts
from linux3d.export import ornament_parts, printable_parts
from linux3d.figures import FIGURES

FIGS = list(FIGURES.values())
# the figures with a standee and a pedestal: Znurt is an ornament only. (Not STANDEES: that
# is the name of the output folder in params.)
STANDEE_FIGS = [f for f in FIGS if f.standee]
KINDS = ("standee", "ornament")  # the band tests run on both
# every printable part by name: the standee and pedestal of the figures that have them,
# both ornament halves of every figure, and the slot gauge
NAMES = ([f"{f.name}_{kind}" for f in FIGS
          for kind in ("standee", "pedestal", "ornament_front", "ornament_back")
          if f.standee or kind.startswith("ornament")]
         + list(coupon_parts()))


def fig_id(fig) -> str:
    """The test id of a figure parameter."""
    return fig.name


def kinds_of(figs: list) -> list:
    """(figure, kind) for the band tests: every figure as an ornament, and as a standee if it
    has one."""
    return [pytest.param(f, kind, id=f"{f.name}-{kind}") for f in figs for kind in KINDS
            if kind == "ornament" or f.standee]


def layout_of(kind: str, fig):
    """The 2D layout of a standee or of an ornament's front half."""
    return relief.layout(fig) if kind == "standee" else ornament.layout(fig)


def view_of(kind: str, fig):
    """The figure the bands were built for: an ornament has its own size and body."""
    return fig if kind == "standee" else ornament.as_ornament(fig)


@pytest.fixture(scope="session")
def parts():
    """Every printable part on the bed, by name."""
    return printable_parts(STANDEE_FIGS) | ornament_parts(FIGS) | coupon_parts()
