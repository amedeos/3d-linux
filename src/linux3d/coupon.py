"""Slot gauge (~15 min): find the clearance between a standee's tenon and the pedestal slot.

- The gauge block prints standing up, like a pedestal. It has four slots, SLOT_GAUGE mm
  wider per side than the tenon, marked with 1 to 4 dots.
- The test tenon prints lying flat, like a standee, so its thickness comes from the
  layers exactly as the real tenon does.

Push the tenon into each slot and keep the clearance that holds firmly but still goes in
by hand. Write it into `params.CLR_SLOT`.
"""

from functools import cache

from build123d import Box, Cylinder, Part, Pos

from . import params as P

TENON = (12.0, 18.0)  # width and length of the test tenon (mm)
DEPTH = P.snap_up(6.0)  # slot depth in the gauge block
BLOCK_H = P.layers(50)  # 10 mm
PITCH, MARGIN, HALF_D = 17.0, 10.0, 7.0


def _box(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> Part:
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


def gauge_block(base_t: float = P.BASE_T) -> Part:
    """The block, on the bed, with four slots across y."""
    w = TENON[0]
    length = 2 * MARGIN + PITCH * (len(P.SLOT_GAUGE) - 1)
    block = _box(0, length, -HALF_D, HALF_D, 0, BLOCK_H)
    for k, clr in enumerate(P.SLOT_GAUGE):
        cx = MARGIN + k * PITCH
        block -= _box(cx - w / 2 - clr, cx + w / 2 + clr, -base_t / 2 - clr,
                      base_t / 2 + clr, BLOCK_H - DEPTH, BLOCK_H + 1)
        for d in range(k + 1):  # k + 1 dots in front of the slot
            dx = (d - k / 2) * 2.0
            block += Pos(cx + dx, -HALF_D + 2.0, BLOCK_H + P.layers(3) / 2) * Cylinder(
                0.7, P.layers(3))
    return block


def test_tenon(base_t: float = P.BASE_T) -> Part:
    """A piece of tenon, printed lying flat like the standees."""
    return _box(-TENON[0] / 2, TENON[0] / 2, 0, TENON[1], 0, base_t)


@cache
def _coupon_parts() -> dict[str, Part]:
    return {"coupon_slot_gauge": gauge_block(), "coupon_test_tenon": test_tenon()}


def coupon_parts() -> dict[str, Part]:
    """The gauge pieces on the bed (built once; the dict is a fresh copy)."""
    return dict(_coupon_parts())
