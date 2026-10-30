"""Previews: the 2D colour check and the cost of a render."""

import numpy as np
from PIL import Image, ImageColor
from shapely.geometry import Polygon, box

from linux3d import ornament, pedestal, render
from linux3d import params as P
from linux3d.figures import FIGURES


def test_mask_keeps_an_island_inside_a_hole():
    """A small island sits in the hole of a frame. Drawn first, it used to be erased by
    the frame's hole, so it vanished from the flat preview (Konqi's band 3)."""
    frame = box(0, 0, 10, 10).difference(box(2, 2, 8, 8))
    island = box(4, 4, 6, 6)
    geom = [island, frame]  # island first: the order that went wrong
    from shapely.geometry import MultiPolygon

    m = np.array(render.mask(MultiPolygon(geom), (0, 0, 10, 10), 10, pad=0), dtype=bool)
    assert m[50, 50]  # the island (row 50 = y 5)
    assert not m[30, 30]  # the hole around it
    assert m[5, 5]  # the frame


def test_mask_keeps_holes():
    ring = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(3, 3), (7, 3), (7, 7), (3, 7)]])
    m = np.array(render.mask(ring, (0, 0, 10, 10), 10, pad=0), dtype=bool)
    assert m[5, 5] and not m[50, 50]


def test_figure_images_builds_the_scene_once(tmp_path, monkeypatch):
    """The pedestal's colour split costs OCCT booleans: build the scene only once, even
    with the GIF."""
    calls = {"scene": 0, "coloured": 0}
    real_scene, real_coloured = render.scene, pedestal.coloured

    def scene(fig):
        calls["scene"] += 1
        return real_scene(fig)

    def coloured(fig):
        calls["coloured"] += 1
        return real_coloured(fig)

    monkeypatch.setattr(render, "scene", scene)
    monkeypatch.setattr(pedestal, "coloured", coloured)
    monkeypatch.setattr(render, "render", lambda *a, **k: None)
    monkeypatch.setattr(render, "gif", lambda frames, *a, **k: list(frames))
    paths = render.figure_images(FIGURES["larry"], tmp_path, with_gif=True)
    assert calls == {"scene": 1, "coloured": 1}
    assert (tmp_path / "larry_flat.png").is_file() and len(paths) == 5


def test_ornament_images_turn_all_the_way_round(tmp_path, monkeypatch):
    """The ornament's GIF is one full turn (front, edge, back): it must not play back."""
    calls = []
    monkeypatch.setattr(render, "render", lambda *a, **k: None)
    monkeypatch.setattr(render, "gif", lambda frames, *a, **k: calls.append((list(frames), k)))
    paths = render.ornament_images(FIGURES["kde_logo"], tmp_path, with_gif=True)
    assert (tmp_path / "kde_logo_flat.png").is_file() and len(paths) == 6
    assert (tmp_path / "kde_logo_hang.png").is_file()
    (frames, kw), = calls
    assert kw["bounce"] is False
    angles = [f["azim"] for f in kw["per_frame"]]
    assert max(angles) - min(angles) >= 330 and len(frames) == len(angles)


def test_hang_preview_drops_the_plumb_line_from_the_hole(tmp_path):
    """The line hangs straight down from the top of the hole, through the middle of the
    hole as drawn, past the mark on the centre of mass of the solids. Larry is not
    symmetric, so a line in the wrong place would show."""
    fig, px = FIGURES["larry"], 8.0
    lay = ornament.layout(fig)
    img = np.array(Image.open(render.hang_preview(fig, tmp_path / "hang.png", px)))
    rows, cols = np.nonzero((img == ImageColor.getrgb(render.PLUMB)).all(axis=2))
    to_px = render._to_px(lay.bands[0].bounds, px)
    hx, hy, r = lay.hole
    line_x, hole_top = to_px(hx, hy + r)
    mark_x, mark_y = to_px(*ornament.mass_centre(fig))
    mark = 1.5 * px + 2
    near = np.abs(rows - mark_y) <= mark
    assert np.abs(cols[~near] - line_x).max() <= 1.5  # one straight vertical line
    assert abs(cols[near].mean() - mark_x) <= 1.0  # the mark is on the centre of mass
    assert abs(rows.min() - hole_top) <= 1.5  # from the top of the hole
    assert rows.max() > mark_y + mark  # down past the centre of mass
    # the drawn hole (background inside the ring) lies evenly on both sides of the line
    row = img[round(to_px(hx, hy)[1])]
    hole = np.nonzero((row == render.BACKGROUND).all(axis=1))[0]
    hole = hole[np.abs(hole - line_x) < (r + ornament.RING_W / 2) * px]
    assert len(hole) > r * px and abs(hole.mean() - line_x) <= 1.0


def test_images_without_gif_remove_an_old_gif(tmp_path, monkeypatch):
    """A GIF from an earlier run would no longer match the new images: five figures kept
    GIFs older than their PNGs."""
    monkeypatch.setattr(render, "render", lambda *a, **k: None)
    monkeypatch.setattr(render, "scene", lambda fig: [])
    old = [tmp_path / kind / "render" / "kde_logo.gif" for kind in (P.STANDEES, P.ORNAMENTS)]
    for path in old:
        path.parent.mkdir(parents=True)
        path.write_bytes(b"GIF89a")
    paths = render.all_images(FIGURES["kde_logo"], tmp_path)
    assert not any(p.exists() for p in old) and not any(p.suffix == ".gif" for p in paths)
