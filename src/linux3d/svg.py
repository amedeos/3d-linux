"""Read an SVG drawing as flat coloured shapes (shapely), ready to become colour bands.

- svgelements parses the file and applies every transform (`reify`).
- Curves become polylines; the fill rule (nonzero or evenodd) is evaluated exactly with
  winding numbers on the faces of the noded outline.
- A stroke becomes its own shape: the path buffered by half the stroke width.
- A gradient counts as one colour: the average of its stops, weighted by their opacity.
- Opacity multiplies down the tree: group opacity x element opacity x fill (or stroke)
  opacity, as a browser shows it.
- `visible()` applies the painter's algorithm: what a shape shows is the shape minus
  everything painted after it.

Coordinates stay in SVG user units, with y flipped so that y points up.
"""

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LinearRing, LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union
from svgelements import SVG, Close, Color, Group, Line, Move, Shape, Use
from svgelements import Path as SvgPath

from .filaments import hex_rgb

NS = "{http://www.w3.org/2000/svg}"
XLINK = "{http://www.w3.org/1999/xlink}href"
SEGMENTS_PER_DRAWING = 3000  # curve sampling: the step is the drawing diagonal / this


@dataclass(frozen=True)
class Shape2D:
    """One painted shape: the fill or the stroke of an SVG element."""

    key: str  # element id (or "#n" for elements without id), plus ":stroke" for strokes
    index: int  # paint order
    kind: str  # "fill" or "stroke"
    colour: str  # "#rrggbb"
    opacity: float  # element opacity times fill/stroke opacity
    geom: BaseGeometry


def fraction(value) -> float:
    """An SVG opacity: a number or a percentage ("0.5", "50%"), clamped to 0..1."""
    if value is None:
        return 1.0
    text = str(value).strip()
    v = float(text[:-1]) / 100 if text.endswith("%") else float(text or 1)
    return min(1.0, max(0.0, v))


def _style(el: ET.Element) -> dict[str, str]:
    style = dict(kv.split(":", 1) for kv in (el.get("style") or "").split(";") if ":" in kv)
    return {k.strip(): v.strip() for k, v in style.items()}


def gradients(path: Path) -> dict[str, tuple[str, float]]:
    """Gradient id -> (average colour, average opacity), following xlink:href chains."""
    root = ET.parse(path).getroot()
    elements = {e.get("id"): e for e in root.iter()
                if e.tag in (NS + "linearGradient", NS + "radialGradient") and e.get("id")}

    def stops(gid: str, depth: int = 0) -> list[tuple[str, float]]:
        e = elements.get(gid)
        if e is None or depth > 10:
            return []
        own = [s for s in e if s.tag == NS + "stop"]
        if not own:
            href = e.get(XLINK) or e.get("href") or ""
            return stops(href.lstrip("#"), depth + 1)
        out = []
        for s in own:
            st = _style(s)
            colour = st.get("stop-color", s.get("stop-color", "#000000"))
            opacity = fraction(st.get("stop-opacity", s.get("stop-opacity", "1")))
            out.append((str(Color(colour).hex)[:7], opacity))
        return out

    table = {}
    for gid in elements:
        s = stops(gid)
        if not s:
            continue
        weight = sum(o for _, o in s) or 1.0
        rgb = [sum(hex_rgb(c)[i] * o for c, o in s) / weight for i in range(3)]
        table[gid] = ("#" + "".join(f"{round(v * 255):02x}" for v in rgb),
                      sum(o for _, o in s) / len(s))
    return table


def _paint(value, raw: str | None, paint_opacity, grads: dict) -> tuple[str, float] | None:
    """(colour, opacity) of a fill or stroke, or None when nothing is painted.

    paint_opacity is the fill-opacity or stroke-opacity. svgelements already folds it into
    the alpha of a plain colour, so it only counts here for gradients.
    """
    if raw is not None and raw.strip().startswith("url("):
        gid = re.search(r"#([^)'\"\s]+)", raw)  # url(#id), url('#id') or url("#id")
        grad = grads.get(gid.group(1)) if gid else None
        return (grad[0], grad[1] * fraction(paint_opacity)) if grad else None
    if value is None or raw == "none" or getattr(value, "value", None) is None:
        return None
    colour = Color(value)
    if colour.alpha == 0:
        return None
    return str(colour.hex)[:7], colour.alpha / 255


def _shapes_with_opacity(node, inherited: float = 1.0):
    """(shape, group opacity x own opacity) in paint order.

    svgelements copies a group's opacity down to its children, and a child's own opacity
    replaces it. Opacity does not inherit in SVG: it multiplies. So we walk the tree and
    read each element's own attribute.
    """
    for child in node:
        own = fraction(child.values.get("attributes", {}).get("opacity"))
        if isinstance(child, (Group, Use)):
            yield from _shapes_with_opacity(child, inherited * own)
        elif isinstance(child, Shape):
            yield child, inherited * own


def _rings(path: SvgPath, step: float) -> list[np.ndarray]:
    """Sample every subpath into a closed polyline (n x 2, y flipped)."""
    rings, current = [], []
    for seg in path:
        if isinstance(seg, Move):
            if len(current) > 2:
                rings.append(np.array(current))
            current = [(seg.end.x, -seg.end.y)]
            continue
        if seg.start is None or seg.end is None:
            continue
        if isinstance(seg, (Line, Close)):
            pts = [seg.end]
        else:
            n = max(2, math.ceil(seg.length(error=1e-4) / step))
            pts = [seg.point(t) for t in np.linspace(0, 1, n + 1)[1:]]
        current.extend((p.x, -p.y) for p in pts)
        if isinstance(seg, Close):
            if len(current) > 2:
                rings.append(np.array(current))
            current = [current[-1]]
    if len(current) > 2:
        rings.append(np.array(current))
    return rings


def _open_lines(path: SvgPath, step: float) -> list[np.ndarray]:
    """Sample every subpath into a polyline, closed only where the SVG closes it."""
    lines, current, closed = [], [], False
    for seg in path:
        if isinstance(seg, Move):
            if len(current) > 1:
                lines.append((np.array(current), closed))
            current, closed = [(seg.end.x, -seg.end.y)], False
            continue
        if seg.start is None or seg.end is None:
            continue
        if isinstance(seg, (Line, Close)):
            pts = [seg.end]
        else:
            n = max(2, math.ceil(seg.length(error=1e-4) / step))
            pts = [seg.point(t) for t in np.linspace(0, 1, n + 1)[1:]]
        current.extend((p.x, -p.y) for p in pts)
        if isinstance(seg, Close):
            closed = True
    if len(current) > 1:
        lines.append((np.array(current), closed))
    return lines


def _winding(point: tuple[float, float], ring: np.ndarray) -> int:
    """Winding number of a closed polyline around a point (any ring, even self-crossing)."""
    x, y = point
    a = ring
    b = np.roll(ring, -1, axis=0)
    cross = (b[:, 0] - a[:, 0]) * (y - a[:, 1]) - (x - a[:, 0]) * (b[:, 1] - a[:, 1])
    up = (a[:, 1] <= y) & (b[:, 1] > y) & (cross > 0)
    down = (a[:, 1] > y) & (b[:, 1] <= y) & (cross < 0)
    return int(up.sum() - down.sum())


def filled_area(rings: list[np.ndarray], rule: str = "nonzero") -> BaseGeometry:
    """The area a fill covers, with the SVG fill rule applied exactly."""
    rings = [r for r in rings if len(r) > 2]
    if not rings:
        return Polygon()
    noded = unary_union([LinearRing(r) for r in rings])
    faces = list(polygonize(noded))
    keep = []
    for face in faces:
        p = face.representative_point()
        w = [_winding((p.x, p.y), r) for r in rings]
        inside = sum(w) != 0 if rule == "nonzero" else sum(abs(v) % 2 for v in w) % 2 == 1
        if inside:
            keep.append(face)
    return shapely.make_valid(unary_union(keep)) if keep else Polygon()


def _stroke_area(path: SvgPath, width: float, step: float, cap: str, join: str) -> BaseGeometry:
    caps = {"butt": "flat", "round": "round", "square": "square"}
    joins = {"miter": "mitre", "round": "round", "bevel": "bevel"}
    parts = []
    for pts, closed in _open_lines(path, step):
        line = LinearRing(pts) if closed and len(pts) > 2 else LineString(pts)
        parts.append(line.buffer(width / 2, cap_style=caps.get(cap, "flat"),
                                 join_style=joins.get(join, "mitre"), mitre_limit=4.0))
    return unary_union(parts) if parts else Polygon()


def load(path: Path) -> list[Shape2D]:
    """Every painted fill and stroke of the drawing, in paint order."""
    svg = SVG.parse(str(path), reify=True)
    grads = gradients(path)
    shapes = []
    elements = list(_shapes_with_opacity(svg))
    bbs = [e.bbox() for e, _ in elements if e.bbox() is not None]
    diag = math.hypot(max(b[2] for b in bbs) - min(b[0] for b in bbs),
                      max(b[3] for b in bbs) - min(b[1] for b in bbs))
    step = diag / SEGMENTS_PER_DRAWING
    for n, (el, opacity) in enumerate(elements):
        v = el.values
        if v.get("display") == "none" or v.get("visibility") == "hidden":
            continue
        key = el.id or f"#{n}"
        p = SvgPath(el)
        fill = _paint(el.fill, v.get("fill"), v.get("fill-opacity"), grads)
        if fill is not None:
            colour, alpha = fill
            area = filled_area(_rings(p, step), v.get("fill-rule", "nonzero"))
            if not area.is_empty:
                shapes.append(Shape2D(key, len(shapes), "fill", colour, opacity * alpha, area))
        stroke = _paint(el.stroke, v.get("stroke"), v.get("stroke-opacity"), grads)
        width = el.stroke_width or 0.0
        if stroke is not None and width > 0:
            colour, alpha = stroke
            area = _stroke_area(p, width, step, v.get("stroke-linecap", "butt"),
                                v.get("stroke-linejoin", "miter"))
            if not area.is_empty:
                shapes.append(Shape2D(key + ":stroke", len(shapes), "stroke", colour,
                                      opacity * alpha, area))
    return shapes


def visible(shapes: list[Shape2D]) -> list[Shape2D]:
    """Painter's algorithm: each shape minus everything painted on top of it."""
    out, covered = [], Polygon()
    for s in reversed(shapes):
        area = s.geom.difference(covered) if not covered.is_empty else s.geom
        covered = unary_union([covered, s.geom])
        if not area.is_empty and area.area > 0:
            out.append(replace(s, geom=area))
    return out[::-1]
