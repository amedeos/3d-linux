import json
import re
import zipfile
from itertools import combinations

import pytest
from conftest import STANDEE_FIGS

from linux3d import ornament, pedestal, relief
from linux3d.export import (
    BED,
    PLAN,
    export_all,
    m600_metadata,
    ornament_plate_name,
    ornament_plates,
    pedestal_plate_name,
    plate_plan,
    plates,
    standee_plate_name,
    write_3mf,
)
from linux3d.figures import FIGURES, figure
from linux3d.params import ORNAMENTS, STANDEES
from linux3d.slicer import CONFIG_ENTRY, M600_ENTRY, config_from_gcode, make_project

FIGS = list(FIGURES.values())
PLATES = plates(STANDEE_FIGS) | ornament_plates(FIGS)


@pytest.mark.parametrize("name", list(PLATES))
def test_plate_fits_the_bed_without_overlaps(name):
    objects, _ = PLATES[name]
    boxes = [part.bounding_box() for _, part, _ in objects]
    for bb in boxes:
        assert bb.min.X >= 0 and bb.min.Y >= 0 and abs(bb.min.Z) < 1e-3
        assert bb.max.X <= BED[0] and bb.max.Y <= BED[1] and bb.max.Z <= BED[2]
    for a, b in combinations(boxes, 2):
        assert a.max.X < b.min.X or b.max.X < a.min.X or a.max.Y < b.min.Y or b.max.Y < a.min.Y


def test_ornament_halves_too_wide_for_the_bed_are_an_error():
    """At 110 mm, Plasma's two halves are 265 mm wide side by side: export must stop, not
    write a plate that hangs over the edge of the bed (checked before any solid is built)."""
    with pytest.raises(ValueError, match="do not fit side by side"):
        ornament_plates([figure("plasma_logo", ornament_h=110.0)])


def test_export_stops_before_writing_when_an_ornament_does_not_fit(tmp_path):
    """The check runs on the 2D layouts first: not even the standees are written, so the
    output folders never hold a half-finished export."""
    with pytest.raises(ValueError, match="do not fit side by side"):
        export_all(tmp_path, [figure("larry"), figure("plasma_logo", ornament_h=110.0)])
    assert not any(tmp_path.iterdir())


@pytest.mark.parametrize("name", list(PLATES))
def test_plate_is_centred_on_the_bed(name):
    # PrusaSlicer arranges around the middle of the bed; the plates start there too
    objects, _ = PLATES[name]
    boxes = [part.bounding_box() for _, part, _ in objects]
    x0, x1 = min(b.min.X for b in boxes), max(b.max.X for b in boxes)
    y0, y1 = min(b.min.Y for b in boxes), max(b.max.Y for b in boxes)
    assert (x0 + x1) / 2 == pytest.approx(BED[0] / 2, abs=0.5)
    assert (y0 + y1) / 2 == pytest.approx(BED[1] / 2, abs=0.5)


def test_one_schedule_per_plate():
    # a standee's M600s would stripe a pedestal, so they never share a plate
    for fig in FIGS:
        standee = [p for p in PLATES if p.startswith(f"{fig.name}_standee")]
        ped = [p for p in PLATES if p.startswith(f"{fig.name}_pedestal")]
        if not fig.standee:  # an ornament only (Znurt)
            assert standee == ped == []
            continue
        assert len(standee) == len(ped) == 1
        assert PLATES[standee[0]][1] == relief.colour_changes(fig)
        change = pedestal.text_change(fig)
        assert PLATES[ped[0]][1] == ([change] if change else [])
    assert PLATES["coupon_slot_gauge"][1] == []


def test_one_plate_per_ornament():
    # both halves on one plate: they have the same colour changes
    for fig in FIGS:
        names = [p for p in PLATES if p.startswith(f"{fig.name}_ornament")]
        assert len(names) == 1
        objects, changes = PLATES[names[0]]
        assert [n for n, _, _ in objects] == [f"{fig.name} ornament front",
                                              f"{fig.name} ornament back"]
        assert changes == ornament.colour_changes(fig)
        assert changes == relief.colour_changes(ornament.as_ornament(fig))


def test_m600_metadata_lists_every_change():
    xml = m600_metadata([(2.6, "white"), (3.4, "red")])
    assert re.findall(r'print_z="([\d.]+)"', xml) == ["2.60", "3.40"]
    assert xml.count('gcode="M600"') == 2
    # the PrusaSlicer 2.9 GUI ignores colour changes without a bed index
    assert xml.count('bed_idx="0"') == 3 and xml.count("<mode ") == 1


@pytest.mark.parametrize("name", ["konqi_standee_black-green-white-red-orange",
                                  "gentoo_logo_pedestal_violet-white", "coupon_slot_gauge",
                                  "plasma_logo_ornament_white-black-orange-green-blue"])
def test_3mf_content(tmp_path, name):
    objects, changes = PLATES[name]
    path = tmp_path / f"{name}.3mf"
    write_3mf(path, objects, changes)
    z = zipfile.ZipFile(path)
    model = z.read("3D/3dmodel.model").decode()
    assert 'unit="millimeter"' in model
    assert re.findall(r'<object [^>]*name="([^"]*)"', model) == [n for n, _, _ in objects]
    if not changes:
        assert M600_ENTRY not in z.namelist()
    else:
        xml = z.read(M600_ENTRY).decode()
        assert re.findall(r'print_z="([\d.]+)"', xml) == [f"{zz:.2f}" for zz, _ in changes]


def test_plan_is_merged_across_exports(tmp_path):
    """Exporting one figure keeps the plates of the figures exported before. Standees and
    ornaments go into their own folders, each with its own plan."""
    plan_path = tmp_path / STANDEES / "3mf" / PLAN
    plan_path.parent.mkdir(parents=True)
    earlier = {"start": "black", "changes": [[2.6, "white"]]}
    plan_path.write_text(json.dumps({"earlier_plate": earlier}), encoding="utf-8")
    small = figure("larry", height=40.0, title="", ornament_h=40.0)
    export_all(tmp_path, [small], coupon=False)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["earlier_plate"] == earlier
    for name, entry in plate_plan(plates([small], coupon=False)).items():
        assert plan[name] == entry
    assert (tmp_path / STANDEES / "3mf" / "larry_standee_black-white.3mf").is_file()
    assert (tmp_path / STANDEES / "stl" / "larry_pedestal.stl").is_file()
    folder = tmp_path / ORNAMENTS
    plan = json.loads((folder / "3mf" / PLAN).read_text(encoding="utf-8"))
    assert plan == plate_plan(ornament_plates([small]))
    assert (folder / "3mf" / "larry_ornament_black-white.3mf").is_file()
    assert (folder / "3mf" / "assembly_preview.3mf").is_file()
    assert {p.name for p in (folder / "stl").iterdir()} == {"larry_ornament_front.stl",
                                                            "larry_ornament_back.stl"}


def test_ornament_only_figure_exports_only_its_ornament(tmp_path):
    """Znurt has no standee: export writes nothing into out/standees, not even the slot
    gauge, and its ornament as usual."""
    report = export_all(tmp_path, [FIGURES["znurt"]])
    assert not (tmp_path / STANDEES).exists()
    assert set(report) == {"znurt_ornament_front", "znurt_ornament_back"}
    assert not any(report.values())
    folder = tmp_path / ORNAMENTS
    assert (folder / "3mf" / "znurt_ornament_violet-white-black-orange.3mf").is_file()
    assert {p.name for p in (folder / "stl").iterdir()} == {"znurt_ornament_front.stl",
                                                            "znurt_ornament_back.stl"}


def test_ornament_only_figure_loses_its_old_standee_outputs(tmp_path):
    """A figure that had a standee in an earlier export: its standee and pedestal files and
    plan entries go (slice would still slice them); other figures' stay."""
    from linux3d.export import remove_standee_outputs

    folder = tmp_path / STANDEES
    old = [folder / "stl" / "larry_standee.stl", folder / "stl" / "larry_pedestal.stl",
           folder / "3mf" / "larry_standee_black-white.3mf",
           folder / "3mf" / "larry_pedestal_black-white.3mf",
           folder / "3mf" / "projects" / "larry_standee_black-white.3mf"]
    kept = [folder / "stl" / "konqi_standee.stl", folder / "3mf" / "larry2_standee_x.3mf"]
    for path in old + kept:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    konqi = {"start": "black", "changes": [[2.6, "green"]]}
    plan = {"larry_standee_black-white": {"start": "black", "changes": [[2.6, "white"]]},
            "larry_pedestal_black-white": {"start": "black", "changes": []},
            "konqi_standee_x": konqi}
    (folder / "3mf" / PLAN).write_text(json.dumps(plan), encoding="utf-8")
    removed = remove_standee_outputs(folder, figure("larry", standee=False))
    assert not any(p.exists() for p in old) and all(p.exists() for p in kept)
    assert json.loads((folder / "3mf" / PLAN).read_text(encoding="utf-8")) == {
        "konqi_standee_x": konqi}
    assert len(removed) == len(old) + 2  # the files and the two plan entries


def test_removing_the_last_standee_removes_the_plan_and_the_preview(tmp_path):
    """An empty plan.json would make slice fail ("no plates"), and the assembly preview
    would still show the standee: both go."""
    from linux3d.export import PREVIEW, remove_standee_outputs

    folder = tmp_path / STANDEES / "3mf"
    folder.mkdir(parents=True)
    (folder / PLAN).write_text(json.dumps({"larry_standee_black-white": {
        "start": "black", "changes": []}}), encoding="utf-8")
    with zipfile.ZipFile(folder / f"{PREVIEW}.3mf", "w") as z:
        z.writestr("3D/3dmodel.model", '<object name="larry pedestal"/>')
    remove_standee_outputs(tmp_path / STANDEES, figure("larry", standee=False))
    assert not (folder / PLAN).exists() and not (folder / f"{PREVIEW}.3mf").exists()


def test_only_figures_defined_as_ornaments_lose_their_standee_outputs():
    """`--set standee=false` for one run (just Larry's ornament) must not delete Larry's
    standee files: only a figure the registry defines as an ornament only loses them."""
    from linux3d.export import defined_ornament_only

    assert defined_ornament_only(FIGURES["znurt"])
    assert not defined_ornament_only(figure("larry", standee=False))


def test_standee_of_an_ornament_only_figure_is_refused():
    """Every standee and pedestal starts at relief.layout(): it refuses Znurt, so no caller
    can build a 294 mm standee for it by passing every figure."""
    with pytest.raises(ValueError, match="ornament only"):
        plates([FIGURES["znurt"]])
    with pytest.raises(ValueError, match="ornament only"):
        pedestal.size(FIGURES["znurt"])


def test_export_builds_plates_and_coupon_once(tmp_path, monkeypatch):
    """plan.json comes from the plates already built, and the gauge's booleans run once."""
    from linux3d import coupon, export

    calls = {"plates": 0, "gauge": 0}
    real_plates, real_gauge = export.plates, coupon.gauge_block

    def counted_plates(*a, **k):
        calls["plates"] += 1
        return real_plates(*a, **k)

    def counted_gauge(*a, **k):
        calls["gauge"] += 1
        return real_gauge(*a, **k)

    monkeypatch.setattr(export, "plates", counted_plates)
    monkeypatch.setattr(coupon, "gauge_block", counted_gauge)
    coupon._coupon_parts.cache_clear()
    try:
        export_all(tmp_path, [figure("larry", height=40.0, title="", ornament_h=40.0)],
                   coupon=True)
    finally:
        coupon._coupon_parts.cache_clear()  # do not keep the counting wrapper's result
    assert calls == {"plates": 1, "gauge": 1}


def test_project_gets_the_config_from_the_gcode(tmp_path):
    gcode = tmp_path / "x.gcode"
    gcode.write_text("; generated by PrusaSlicer 2.9.6\nG1 X1\n; prusaslicer_config = begin\n"
                     "; binary_gcode = 0\n; layer_height = 0.2\n; prusaslicer_config = end\n",
                     encoding="utf-8")
    config = config_from_gcode(gcode)
    assert "; binary_gcode = 1" in config and "; layer_height = 0.2" in config
    plate = tmp_path / "plate.3mf"
    objects, changes = PLATES[standee_plate_name(FIGURES["larry"])]
    write_3mf(plate, objects, changes)
    project = tmp_path / "projects" / "plate.3mf"
    make_project(plate, config, project)
    assert zipfile.ZipFile(project).read(CONFIG_ENTRY).decode() == config


def test_plan_starts_each_plate_in_its_first_filament():
    """plan.json gives the filament each plate starts with, from the design: slice writes it
    into the project as the filament colour (Znurt starts in violet, not in orange)."""
    plan = plate_plan(PLATES)
    for fig in STANDEE_FIGS:
        assert plan[standee_plate_name(fig)]["start"] == fig.bands[0]
        assert plan[pedestal_plate_name(fig)]["start"] == fig.pedestal_colour
    for fig in FIGS:
        assert plan[ornament_plate_name(fig)]["start"] == fig.bands[0]
    assert plan["coupon_slot_gauge"]["start"] == "grey"


@pytest.mark.parametrize("objects, message", [
    ([("a", None, "black"), ("b", None, "white")], "must start in one filament, not black, "
                                                   "white"),
    ([], "has no objects"),
])
def test_plate_without_one_start_filament_is_refused(tmp_path, objects, message):
    """A plate has one filament until its first M600, so a project has one filament colour.
    The plates are checked before anything is written into their folder."""
    from linux3d.export import _write

    with pytest.raises(ValueError, match=message):
        _write(tmp_path / "out", {}, {"p": (objects, [])}, [])
    assert not (tmp_path / "out").exists()


def test_export_reports_posts_and_leans():
    from linux3d.export import stability_notes

    notes = stability_notes([FIGURES["konqi"], FIGURES["gentoo_logo"], FIGURES["larry"]])
    assert any(n.startswith("konqi: post under") for n in notes)
    assert any(n.startswith("gentoo_logo: centre of mass") and "0.7°" in n for n in notes)
    assert not any(n.startswith("larry") for n in notes)
