"""Parametric Linux logos and mascots, printed as layered-colour standees on pedestals and
as Christmas tree ornaments."""

USAGE = """\
usage: linux3d COMMAND [FIGURE ...] [options]

commands:
  list      the figures and their colour bands
  export    STL files and 3MF plates in out/standees and out/ornaments; exit 1 on problems
  slice     slice the 3MF plates with the PrusaSlicer CLI: times, M600 check, projects
  render    PNG previews in out/standees/render and out/ornaments/render (--gif: a GIF too)

options (for export and render; they change every FIGURE given, or all of them):
  --height MM            height of the standee's drawing (ornament: --set ornament_h=MM)
  --bands A,B,...        filaments from the bed up, e.g. --bands black,white
  --set KEY=VALUE        any parameter of figures.Figure, e.g. --set margin=2
  --material petg|pla    filament profile for slice (default petg)

examples:
  uv run linux3d export gentoo_logo larry
  uv run linux3d export larry --height 120 --set text_colour=none
  uv run linux3d render konqi --bands black,green,white,red,gold
  uv run linux3d export larry --set ornament_h=80
"""


def _figures(names: list[str], sets: list[tuple[str, str]]) -> list:
    from .figures import FIGURES, figure, parse_value

    figs = []
    for name in names or list(FIGURES):
        base = figure(name)
        changes = {key: parse_value(base, key, value) for key, value in sets}
        figs.append(figure(name, **changes))
    return figs


def _fail(message: str) -> None:
    import sys

    print(f"linux3d: {message}\n\n{USAGE}", file=sys.stderr)
    sys.exit(2)


def main(argv: list[str] | None = None) -> None:
    import sys

    from .filaments import MATERIALS

    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "help"):
        print(USAGE)
        sys.exit(0)
    command, rest = args[0], args[1:]
    names, sets, flags, material = [], [], [], "petg"
    while rest:
        a = rest.pop(0)
        if a in ("--height", "--bands", "--set", "--material"):
            if not rest or rest[0].startswith("--"):
                _fail(f"{a} needs a value")
            value = rest.pop(0)
            if a == "--set":
                key, sep, value = value.partition("=")
                if not sep:
                    _fail(f"--set needs KEY=VALUE, not {key!r}")
                sets.append((key.strip(), value.strip()))
            elif a == "--material":
                material = value.lower()
            else:
                sets.append((a[2:], value))
        elif a.startswith("--"):
            flags.append(a)
        else:
            names.append(a)
    if material not in MATERIALS:
        _fail(f"unknown material {material!r}; choose from {', '.join(MATERIALS)}")
    if command in ("export", "render"):
        try:
            figs = _figures(names, sets)
        except (KeyError, ValueError) as e:
            _fail(str(e).strip("'\""))

    if command == "list":
        from .figures import FIGURES

        for f in FIGURES.values():
            print(f"{f.name:12s} {f.height:5.0f} mm  {' -> '.join(f.bands):40s} "
                  f"pedestal {f.pedestal_colour}"
                  + (f", lettering {f.text_colour}" if f.text_colour else "")
                  + f"; ornament {f.ornament_h:.0f} mm")
    elif command == "export":
        from .export import export_all
        from .params import OUT

        try:
            report = export_all(OUT, figs)
        except ValueError as e:  # e.g. a figure that cannot stand
            _fail(str(e))
        sys.exit(1 if any(report.values()) else 0)
    elif command == "slice":
        from .slicer import slice_all

        sys.exit(slice_all(material=material))
    elif command == "render":
        from .render import all_images

        for fig in figs:
            for path in all_images(fig, with_gif="--gif" in flags):
                print("wrote", path)
    else:
        print(f"unknown command {command!r}\n\n{USAGE}")
        sys.exit(2)
