"""Previews: the 2D colour check and the cost of a render."""

import numpy as np
from shapely.geometry import Polygon, box

from linux3d import pedestal, render
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
    assert (tmp_path / "kde_logo_flat.png").is_file() and len(paths) == 5
    (frames, kw), = calls
    assert kw["bounce"] is False
    angles = [f["azim"] for f in kw["per_frame"]]
    assert max(angles) - min(angles) >= 330 and len(frames) == len(angles)
