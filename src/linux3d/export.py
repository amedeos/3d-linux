"""Export the printable parts: STL files (out/stl) and ready-made 3MF plates (out/3mf).

- One STL per part, already in its print orientation.
- One 3MF per print job ("plate"), centred on the Prusa MK4 bed, with names and colours.
  A standee plate carries all its colour changes (one M600 per band) as PrusaSlicer
  metadata, so they are already set when you open the file. A pedestal plate carries the
  M600 of its lettering.
- plan.json: the colour changes each plate must have, written from the design. slicer.py
  checks the real G-code against it, not against the 3MF it is checking.
- assembly_preview.3mf: every figure standing on its pedestal, only for viewing.

Exits with status 1 if any part fails a check, so scripts and CI can rely on it.
"""

import json
import sys
import tempfile
import zipfile
from pathlib import Path

import trimesh
from build123d import Color, Mesher, Part, Pos, export_stl

from . import params as P
from . import pedestal, relief
from .coupon import coupon_parts
from .figures import FIGURES, Figure
from .filaments import FILAMENTS

BED = P.BED
BED_CENTRE = (BED[0] / 2, BED[1] / 2)  # PrusaSlicer arranges around the middle of the bed
STL_TOLERANCE = (0.01, 0.1)  # linear (mm), angular (rad)
PLAN = "plan.json"

Plate = tuple[list[tuple[str, Part, str]], list[tuple[float, str]]]


def standee_plate_name(fig: Figure) -> str:
    return f"{fig.name}_standee_{'-'.join(fig.bands)}"


def pedestal_plate_name(fig: Figure) -> str:
    change = pedestal.text_change(fig)
    return f"{fig.name}_pedestal_{fig.pedestal_colour}" + (f"-{change[1]}" if change else "")


def printable_parts(figs: list[Figure]) -> dict[str, Part]:
    """name -> part on the bed (z = 0), in its print orientation."""
    parts = {}
    for fig in figs:
        parts[f"{fig.name}_standee"] = relief.make_figure(fig)
        parts[f"{fig.name}_pedestal"] = pedestal.print_pose(fig, pedestal.make_pedestal(fig))
    return parts


def check(part: Part) -> list[str]:
    """Problems with the CAD solid itself (empty list = fine)."""
    problems = []
    bb = part.bounding_box()
    if not part.is_valid:
        problems.append("invalid solid")
    if abs(bb.min.Z) > 1e-3:
        problems.append(f"not on the bed (zmin={bb.min.Z:.3f})")
    if bb.size.X > BED[0] or bb.size.Y > BED[1] or bb.size.Z > BED[2]:
        problems.append(f"larger than the bed {bb.size}")
    if len(part.solids()) != 1:
        problems.append(f"{len(part.solids())} separate bodies")
    return problems


def write_stl(part: Part, path: Path) -> list[str]:
    """Write the STL and check the mesh that a slicer will actually load."""
    export_stl(part, path, tolerance=STL_TOLERANCE[0], angular_tolerance=STL_TOLERANCE[1])
    mesh = trimesh.load(path)
    return [] if mesh.is_watertight else ["mesh not watertight"]


def mesh_problems(part: Part) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        return write_stl(part, Path(tmp) / "part.stl")


def _centred(part: Part, cx: float = BED_CENTRE[0], cy: float = BED_CENTRE[1]) -> Part:
    """Move a part (already lying on z=0) so the centre of its footprint is at (cx, cy)."""
    bb = part.bounding_box()
    return Pos(cx - (bb.min.X + bb.max.X) / 2, cy - (bb.min.Y + bb.max.Y) / 2, 0) * part


def _on_bed(part: Part, x_min: float, y_min: float) -> Part:
    """Move a part (already lying on z=0) so its footprint starts at (x_min, y_min)."""
    bb = part.bounding_box()
    return Pos(x_min - bb.min.X, y_min - bb.min.Y, 0) * part


def _row(parts: list[Part], gap: float = 8.0, y_centre: float = BED[1] / 2) -> list[Part]:
    """Lay parts out left to right, centred on the bed."""
    widths = [p.bounding_box().size.X for p in parts]
    x = (BED[0] - sum(widths) - gap * (len(parts) - 1)) / 2
    placed = []
    for part, w in zip(parts, widths):
        placed.append(_on_bed(part, x, y_centre - part.bounding_box().size.Y / 2))
        x += w + gap
    return placed


def plates(figs: list[Figure], coupon: bool = True) -> dict[str, Plate]:
    """plate name -> ([(object name, part on the bed, colour)], colour changes).

    A colour change is (print_z, new filament): the M600 comes before the layer at print_z.
    The object colour is the starting filament.
    """
    out = {}
    for fig in figs:
        out[standee_plate_name(fig)] = (
            [(f"{fig.name} standee", _centred(relief.make_figure(fig)), fig.bands[0])],
            relief.colour_changes(fig))
        change = pedestal.text_change(fig)
        part = pedestal.print_pose(fig, pedestal.make_pedestal(fig))
        out[pedestal_plate_name(fig)] = (
            [(f"{fig.name} pedestal", _centred(part), fig.pedestal_colour)],
            [change] if change else [])
    if coupon:
        cp = coupon_parts()
        out["coupon_slot_gauge"] = (
            [(n, p, "grey") for n, p in zip(cp, _row(list(cp.values())))], [])
    return out


def planned_changes(all_plates: dict[str, Plate]) -> dict[str, list[list]]:
    """plate name -> [[print_z, filament], ...] (JSON friendly)."""
    return {name: [[round(z, 2), c] for z, c in changes]
            for name, (_, changes) in all_plates.items()}


def _named(part: Part, name: str, colour: str) -> Part:
    part = part.moved(Pos())  # a copy: the cached parts must not be changed
    part.label = name
    part.color = Color(FILAMENTS[colour])
    return part


def m600_metadata(changes: list[tuple[float, str]]) -> str:
    """PrusaSlicer's colour-change list, as stored inside its 3MF files."""
    # bed_idx: PrusaSlicer 2.9 keeps colour changes per bed (multiple beds); without it the
    # GUI silently drops them. Older versions ignore the attribute.
    codes = "".join(
        f'<code bed_idx="0" print_z="{z:.2f}" type="0" extruder="1" '
        f'color="{FILAMENTS[c]}" extra="" gcode="M600"/>\n' for z, c in changes)
    return ('<?xml version="1.0" encoding="utf-8"?>\n<custom_gcodes_per_print_z>\n'
            f'{codes}<mode bed_idx="0" value="SingleExtruder"/>\n'
            '</custom_gcodes_per_print_z>\n')


def write_3mf(path: Path, objects: list[tuple[str, Part, str]],
              changes: list[tuple[float, str]] | None = None) -> None:
    mesher = Mesher()
    for name, part, colour in objects:
        mesher.add_shape(_named(part, name, colour), linear_deflection=STL_TOLERANCE[0],
                         angular_deflection=STL_TOLERANCE[1])
    mesher.write(str(path))
    if changes:
        with zipfile.ZipFile(path, "a", zipfile.ZIP_DEFLATED) as z:
            z.writestr("Metadata/Prusa_Slicer_custom_gcode_per_print_z.xml",
                       m600_metadata(changes))


def assembly_preview(figs: list[Figure], gap: float = 20.0) -> list[tuple[str, Part, str]]:
    """Every figure standing on its pedestal, side by side (view only)."""
    items, x = [], 0.0
    for fig in figs:
        parts = [(f"{fig.name} band {k}", p, c)
                 for k, (p, c) in enumerate(relief.coloured(fig))]
        parts += [(f"{fig.name} pedestal", p, c) for p, c in pedestal.coloured(fig)]
        s = pedestal.size(fig)
        x0 = min(s.x0, -relief.layout(fig).size[0] / 2)
        x += -x0
        items += [(n, Pos(x, 0, 0) * p, c) for n, p, c in parts]
        x += max(s.x1, relief.layout(fig).size[0] / 2) + gap
    return items


def export_all(out: Path, figs: list[Figure] | None = None,
               coupon: bool = True) -> dict[str, list[str]]:
    """Write every STL into out/stl and the 3MF plates into out/3mf; return the problems."""
    figs = figs if figs is not None else list(FIGURES.values())
    stl_dir, mf_dir = out / "stl", out / "3mf"
    stl_dir.mkdir(parents=True, exist_ok=True)
    mf_dir.mkdir(parents=True, exist_ok=True)
    parts = printable_parts(figs) | (coupon_parts() if coupon else {})
    report = {}
    for name, part in parts.items():
        problems = check(part) + write_stl(part, stl_dir / f"{name}.stl")
        report[name] = problems
        status = "OK" if not problems else "; ".join(problems)
        print(f"{name:24s} {part.volume / 1000:6.1f} cm3  {status}")
    all_plates = plates(figs, coupon)
    for name, (objects, changes) in all_plates.items():
        write_3mf(mf_dir / f"{name}.3mf", objects, changes)
        note = ", ".join(f"Z {z:.2f} -> {c}" for z, c in changes)
        print(f"{name + '.3mf':52s} {f'M600 at {note}' if note else 'no colour change'}")
    plan_path = mf_dir / PLAN  # keep the plates of figures exported earlier
    plan = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.is_file() else {}
    plan.update(planned_changes(all_plates))
    plan_path.write_text(json.dumps(plan, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    write_3mf(mf_dir / "assembly_preview.3mf", assembly_preview(figs))
    print(f"{'assembly_preview.3mf':52s} view only")
    return report


if __name__ == "__main__":
    names = [a for a in sys.argv[1:] if not a.startswith("-")]
    result = export_all(Path("out"), [FIGURES[n] for n in names] if names else None)
    sys.exit(1 if any(result.values()) else 0)
