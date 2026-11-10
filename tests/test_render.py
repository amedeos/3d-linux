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


def test_ornament_only_figure_gets_no_standee_images(tmp_path, monkeypatch):
    """Znurt has no standee: all_images() makes only its ornament's images."""
    monkeypatch.setattr(render, "render", lambda *a, **k: None)
    paths = render.all_images(FIGURES["znurt"], tmp_path)
    assert paths and all(p.parent == tmp_path / P.ORNAMENTS / "render" for p in paths)
    assert not (tmp_path / P.STANDEES).exists()


def test_ornament_only_figure_loses_its_old_standee_images(tmp_path, monkeypatch):
    """Images of a standee from a run when the figure still had one no longer match."""
    monkeypatch.setattr(render, "render", lambda *a, **k: None)
    old = [tmp_path / P.STANDEES / "render" / f"znurt{view}.png"
           for view in render.STANDEE_VIEWS]
    for path in old:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    render.all_images(FIGURES["znurt"], tmp_path)
    assert not any(p.exists() for p in old)


def test_one_off_ornament_only_keeps_the_standee_images(tmp_path, monkeypatch):
    """`--set standee=false` for one run: Larry's standee images stay."""
    from linux3d.figures import figure

    monkeypatch.setattr(render, "ornament_images", lambda fig, out, with_gif=False: [])
    old = tmp_path / P.STANDEES / "render" / "larry.png"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"x")
    render.all_images(figure("larry", standee=False), tmp_path)
    assert old.exists()


def test_render_fits_what_the_camera_sees():
    """A long bar seen in an upright image: the fit uses the projected outline, so the bar
    reaches the margin on its long side and is not cut off (fitting a sphere to the image
    height cut Znurt's saucer off)."""
    from build123d import Box

    pts = render._points([(Box(120, 6, 6), "black")])
    size = (400, 600)
    for elev, azim in ((12, -70), (90, -90), (30, 10)):
        focal = render.fit(pts, size, elev, azim)
        eye, rot, _ = render._camera(pts, elev, azim)
        cam = (pts - eye) @ rot.T
        x = focal * cam[:, 0] / -cam[:, 2]
        y = focal * cam[:, 1] / -cam[:, 2]
        room = (1 - 2 * render.MARGIN) * np.array(size) / 2
        assert np.abs(x).max() <= room[0] + 1e-6 and np.abs(y).max() <= room[1] + 1e-6
        assert max(np.abs(x).max() / room[0], np.abs(y).max() / room[1]) > 0.999


def test_gif_frames_share_one_focal_length(tmp_path, monkeypatch):
    """Fitted frame by frame, a turning object would grow and shrink."""
    from build123d import Box

    seen = []
    monkeypatch.setattr(render, "render", lambda items, path, **k: seen.append(k["focal"]))
    monkeypatch.setattr(render.Image, "open", lambda path: Image.new("RGB", (4, 4)))
    turn = [{"elev": 14, "azim": a} for a in range(0, 360, 45)]
    items = [(Box(120, 6, 30), "black")]
    render.gif((items for _ in turn), tmp_path / "turn.gif", size=(300, 200), per_frame=turn)
    assert len(seen) == len(turn) and len(set(seen)) == 1
    assert seen[0] == min(render.fit(render._points(items), (300, 200), 14, a["azim"])
                          for a in turn)


def test_wide_ornament_gets_a_landscape_frame(tmp_path, monkeypatch):
    """render() fits the height of the image: Znurt's saucer, 2.8 times as wide as high,
    lost both ends in the upright frame. A square ornament keeps the upright frame."""
    sizes = {}
    monkeypatch.setattr(render, "render", lambda items, path, **k: sizes.update({path.name: k}))
    monkeypatch.setattr(render, "gif", lambda frames, path, **k: sizes.update({path.name: k}))
    for name in ("znurt", "kde_logo"):
        render.ornament_images(FIGURES[name], tmp_path, with_gif=True)
    for view in ("znurt.png", "znurt_back.png", "znurt.gif"):
        w, h = sizes[view]["size"]
        assert w == 2 * h
    assert sizes["kde_logo.png"]["size"] == (800, 900)
    assert sizes["kde_logo.gif"]["size"] == (500, 560)


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
