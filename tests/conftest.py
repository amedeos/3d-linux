"""Shared fixtures: every figure is built once per test session (building takes ~30 s)."""

import pytest

from linux3d import ornament, relief
from linux3d.coupon import coupon_parts
from linux3d.export import ornament_parts, printable_parts
from linux3d.figures import FIGURES

FIGS = list(FIGURES.values())
KINDS = ("standee", "ornament")  # the band tests run on both


def layout_of(kind: str, fig):
    """The 2D layout of a standee or of an ornament's front half."""
    return relief.layout(fig) if kind == "standee" else ornament.layout(fig)


def view_of(kind: str, fig):
    """The figure the bands were built for: an ornament has its own size and body."""
    return fig if kind == "standee" else ornament.as_ornament(fig)


@pytest.fixture(scope="session")
def parts():
    """Every printable part on the bed, by name."""
    return printable_parts(FIGS) | ornament_parts(FIGS) | coupon_parts()
