"""Headless previews: a small numpy z-buffer rasteriser (no OpenGL needed).

Smooth shading inside each CAD face, crisp edges between faces, outlines from depth and
normal discontinuities. Good enough to judge shapes and to make listing images.
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image

from .filaments import rgb
from .params import ORNAMENTS, OUT, STANDEES


def _rgb(color) -> np.ndarray:
    return np.array(rgb(color) if isinstance(color, str) else color, dtype=float)


def _mesh(shape, tolerance: float):
    """Triangles plus per-vertex normals averaged within each CAD face."""
    tris, norms = [], []
    shapes = shape if isinstance(shape, (list, tuple)) else [shape]
    for face in (f for sh in shapes for f in sh.faces()):
        verts, idx = face.tessellate(tolerance, 0.2)
        if not idx:
            continue
        v = np.array([[p.X, p.Y, p.Z] for p in verts])
        t = np.array(idx)
        fn = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
        vn = np.zeros_like(v)
        for k in range(3):
            np.add.at(vn, t[:, k], fn)
        vn /= np.linalg.norm(vn, axis=1, keepdims=True) + 1e-12
        tris.append(v[t])
        norms.append(vn[t])
    if not tris:
        return np.zeros((0, 3, 3)), np.zeros((0, 3, 3))
    return np.concatenate(tris), np.concatenate(norms)


def _look_at(eye, target, up=(0, 0, 1)):
    f = np.asarray(target, float) - eye
    f /= np.linalg.norm(f)
    r = np.cross(f, up)
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    return np.stack([r, u, -f])  # rows: camera x, y, z (camera looks along -z)


def render(items, path, elev=28.0, azim=-60.0, zoom=1.0, size=(900, 700), ss=2,
           target=None, distance=None, tolerance=0.08, background=((0.93, 0.92, 0.95),
                                                                (0.72, 0.70, 0.76))):
    """Render [(shape, colour), ...] to `path`. Angles in degrees, azim around +z."""
    meshes = [(*_mesh(s, tolerance), _rgb(c)) for s, c in items]
    pts = np.concatenate([m[0].reshape(-1, 3) for m in meshes if len(m[0])])
    lo, hi = pts.min(0), pts.max(0)
    center = (lo + hi) / 2 if target is None else np.asarray(target, float)
    radius = np.linalg.norm(hi - lo) / 2
    el, az = np.radians(elev), np.radians(azim)
    direction = np.array([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)])
    dist = distance or radius * 3.2
    eye = center + direction * dist
    rot = _look_at(eye, center)
    w, h = size[0] * ss, size[1] * ss
    focal = 0.5 * h * dist / (radius * 1.15) * zoom

    zbuf = np.full((h, w), np.inf)
    nbuf = np.zeros((h, w, 3))
    cbuf = np.zeros((h, w, 3))
    light = rot.T @ np.array([-0.45, 0.65, 0.62])
    light /= np.linalg.norm(light)
    fill = rot.T @ np.array([0.6, -0.2, 0.75])
    fill /= np.linalg.norm(fill)

    for tri, nrm, base in meshes:
        if not len(tri):
            continue
        cam = (tri - eye) @ rot.T  # (n, 3, 3) camera space
        z = -cam[..., 2]
        ok = (z > 1e-3).all(1)
        cam, z, nrm = cam[ok], z[ok], nrm[ok]
        sx = w / 2 + focal * cam[..., 0] / z
        sy = h / 2 - focal * cam[..., 1] / z
        for i in range(len(sx)):
            x0, x1 = int(max(sx[i].min(), 0)), int(min(np.ceil(sx[i].max()), w - 1))
            y0, y1 = int(max(sy[i].min(), 0)), int(min(np.ceil(sy[i].max()), h - 1))
            if x1 < x0 or y1 < y0:
                continue
            gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            (ax_, bx, cx), (ay, by, cy) = sx[i], sy[i]
            den = (by - cy) * (ax_ - cx) + (cx - bx) * (ay - cy)
            if abs(den) < 1e-9:
                continue
            l0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
            l1 = ((cy - ay) * (gx - cx) + (ax_ - cx) * (gy - cy)) / den
            l2 = 1 - l0 - l1
            inside = (l0 >= -1e-6) & (l1 >= -1e-6) & (l2 >= -1e-6)
            if not inside.any():
                continue
            iz = l0 / z[i, 0] + l1 / z[i, 1] + l2 / z[i, 2]  # perspective-correct
            depth = 1 / np.where(inside, iz, 1e-12)
            sub = zbuf[y0:y1 + 1, x0:x1 + 1]
            win = inside & (depth < sub)
            if not win.any():
                continue
            sub[win] = depth[win]
            n = (l0[..., None] * nrm[i, 0] / z[i, 0] + l1[..., None] * nrm[i, 1] / z[i, 1]
                 + l2[..., None] * nrm[i, 2] / z[i, 2]) / iz[..., None]
            nbuf[y0:y1 + 1, x0:x1 + 1][win] = n[win]
            cbuf[y0:y1 + 1, x0:x1 + 1][win] = base

    hit = np.isfinite(zbuf)
    n = nbuf / (np.linalg.norm(nbuf, axis=2, keepdims=True) + 1e-12)
    view = direction  # towards the camera
    flip = (n @ view) < 0
    n[flip] *= -1
    diff = np.clip(n @ light, 0, 1)
    diff2 = np.clip(n @ fill, 0, 1)
    half = light + view
    half /= np.linalg.norm(half)
    spec = np.clip(n @ half, 0, 1) ** 40
    shade = 0.28 + 0.62 * diff + 0.18 * diff2
    img = cbuf * shade[..., None] + 0.22 * spec[..., None]

    # outlines from depth / normal discontinuities
    zf = np.where(hit, zbuf, zbuf[hit].max() * 1.5 if hit.any() else 1)
    edge = np.zeros_like(zf, dtype=bool)
    for axis in (0, 1):  # compare each pixel with its next neighbour (no wrap-around)
        a = [slice(None)] * 2
        b = [slice(None)] * 2
        a[axis], b[axis] = slice(None, -1), slice(1, None)
        a, b = tuple(a), tuple(b)
        dz = np.abs(zf[a] - zf[b])
        dn = 1 - np.sum(n[a] * n[b], axis=2)
        edge[a] |= (dz > 0.004 * zf[a]) | ((dn > 0.35) & hit[a])
    img[edge & hit] *= 0.35

    top, bottom = (np.array(c) for c in background)
    t = np.linspace(0, 1, h)[:, None, None]
    bg = top * (1 - t) + bottom * t
    out = np.where(hit[..., None], img, np.broadcast_to(bg, img.shape))
    out = (np.clip(out, 0, 1) * 255).astype(np.uint8)
    Image.fromarray(out).resize(size, Image.LANCZOS).save(path)


def gif(frames_items, path, duration=80, per_frame=None, bounce=True, **kw):
    """Render an iterable of item lists into an animated GIF that plays forth and back
    (bounce=False: it only plays forth, for a full turn).

    per_frame: optional list of extra render() arguments, one dict per frame (camera moves).
    """
    frames = list(frames_items)
    if not frames:
        raise ValueError("gif() needs at least one frame")
    path = Path(path)
    tmp_paths = [path.with_suffix(f".{k:03d}.png") for k in range(len(frames))]
    try:
        images = []
        for k, (items, tmp) in enumerate(zip(frames, tmp_paths)):
            render(items, tmp, **kw, **(per_frame[k] if per_frame else {}))
            images.append(Image.open(tmp).convert("P", palette=Image.ADAPTIVE))
        seq = images + images[-2:0:-1] if bounce else images
        seq[0].save(path, save_all=True, append_images=seq[1:], duration=duration, loop=0)
    finally:
        for tmp in tmp_paths:
            tmp.unlink(missing_ok=True)


# straight from the front, a little from above and from the right
FRONT = {"elev": 12, "azim": -70, "zoom": 1.25}
FLAT = {"elev": 90, "azim": -90, "zoom": 1.3}  # the print pose, seen from above


def scene(fig) -> list:
    """The figure standing in its pedestal, coloured as printed."""
    from . import pedestal, relief

    return relief.coloured(fig) + pedestal.coloured(fig)


def mask(geom, bounds, px_per_mm: float, pad: int = 10) -> Image.Image:
    """A 1-bit image of a geometry (y up), inside bounds = (x0, y0, x1, y1) plus pad pixels.

    Each polygon gets its own layer (outside filled, holes cleared), and the layers are
    OR-ed. Drawing them all on one image would let a later polygon's hole erase an island
    that sits inside it.
    """
    from PIL import ImageChops, ImageDraw

    from .relief import polygons

    x0, y0, x1, y1 = bounds
    size = (int((x1 - x0) * px_per_mm) + 2 * pad, int((y1 - y0) * px_per_mm) + 2 * pad)

    def pts(coords):
        return [((x - x0) * px_per_mm + pad, (y1 - y) * px_per_mm + pad) for x, y in coords]

    out = Image.new("1", size, 0)
    for poly in polygons(geom):
        layer = Image.new("1", size, 0)
        draw = ImageDraw.Draw(layer)
        draw.polygon(pts(poly.exterior.coords), fill=1)
        for hole in poly.interiors:
            draw.polygon(pts(hole.coords), fill=0)
        out = ImageChops.logical_or(out, layer)
    return out


def flat_preview(fig, path: Path, px_per_mm: float = 8.0, bands=None) -> Path:
    """The standee (or other bands of the figure, e.g. an ornament's) seen from the front
    in 2D, one colour per band: check the colour map."""
    from .filaments import FILAMENTS
    from .relief import layout

    bands = layout(fig).bands if bands is None else bands
    bounds = bands[0].bounds
    img = None
    for band, name in zip(bands, fig.bands):
        m = mask(band, bounds, px_per_mm)
        if img is None:
            img = Image.new("RGB", m.size, (214, 222, 230))
        img.paste(FILAMENTS[name], mask=m)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def figure_images(fig, out: Path, with_gif: bool = False) -> list[Path]:
    """Every image of one figure: standing, from the side, and lying as printed."""
    from . import relief

    out.mkdir(parents=True, exist_ok=True)
    paths = [out / f"{fig.name}.png", out / f"{fig.name}_side.png",
             out / f"{fig.name}_print.png", flat_preview(fig, out / f"{fig.name}_flat.png")]
    items = scene(fig)  # once: the pedestal colours cost two OCCT booleans
    render(items, paths[0], size=(800, 900), **FRONT)
    render(items, paths[1], size=(800, 900), elev=18, azim=-20, zoom=1.25)
    render(relief.coloured(fig, stand=False), paths[2], size=(800, 900), **FLAT)
    if with_gif:  # the camera swings from the left to the right of the figure
        paths.append(out / f"{fig.name}.gif")
        turn = [{"elev": 14, "azim": -90 + a} for a in range(-50, 51, 10)]
        gif((items for _ in turn), paths[-1], size=(500, 560), zoom=1.25, per_frame=turn)
    return paths


def ornament_images(fig, out: Path, with_gif: bool = False) -> list[Path]:
    """Every image of one ornament: hanging (from the front and from the back), flat, and
    both halves lying on the plate."""
    from build123d import Pos

    from . import ornament

    out.mkdir(parents=True, exist_ok=True)
    lay = ornament.layout(fig)
    paths = [out / f"{fig.name}.png", out / f"{fig.name}_back.png", out / f"{fig.name}_print.png",
             flat_preview(fig, out / f"{fig.name}_flat.png", bands=lay.bands)]
    items = ornament.coloured(fig)  # once: both halves, turned over and hung up
    render(items, paths[0], size=(800, 900), **FRONT)
    render(items, paths[1], size=(800, 900), **{**FRONT, "azim": FRONT["azim"] + 180})
    # the plate: the front half on the left, the mirrored back half on the right
    shift = max(abs(v) for v in lay.bands[0].bounds[::2]) + 4.0
    plate = [(Pos(-shift, 0, 0) * p, f) for p, f in zip(ornament.band_parts(fig), fig.bands)]
    plate += [(Pos(shift, 0, 0) * p, f)
              for p, f in zip(ornament.band_parts(fig, back=True), fig.bands)]
    render(plate, paths[2], size=(1000, 700), **FLAT)
    if with_gif:  # one full turn: the front, the edge, the back
        paths.append(out / f"{fig.name}.gif")
        turn = [{"elev": 14, "azim": -90 + a} for a in range(0, 360, 15)]
        gif((items for _ in turn), paths[-1], size=(500, 560), zoom=1.25, per_frame=turn,
            bounce=False)
    return paths


def all_images(fig, out: Path = OUT, with_gif: bool = False) -> list[Path]:
    """The standee's images into out/standees/render, the ornament's into
    out/ornaments/render."""
    return (figure_images(fig, out / STANDEES / "render", with_gif)
            + ornament_images(fig, out / ORNAMENTS / "render", with_gif))


def main(argv: list[str]) -> None:
    from .figures import FIGURES

    args = [a for a in argv if not a.startswith("--")]
    for name in args or list(FIGURES):
        for path in all_images(FIGURES[name], with_gif="--gif" in argv):
            print("wrote", path)


if __name__ == "__main__":
    main(sys.argv[1:])
