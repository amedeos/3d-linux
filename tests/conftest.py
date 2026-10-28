"""Shared fixtures: every figure is built once per test session (building takes ~30 s)."""

import pytest

from linux3d.coupon import coupon_parts
from linux3d.export import printable_parts
from linux3d.figures import FIGURES

FIGS = list(FIGURES.values())


@pytest.fixture(scope="session")
def parts():
    """Every printable part on the bed, by name."""
    return printable_parts(FIGS) | coupon_parts()
