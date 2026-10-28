# AGENTS.md

Guidance for coding agents working in this repository.

## Project

Parametric, printable Linux logos and mascots: the Gentoo "g" logo, Larry the Cow, the KDE logo, the Plasma logo and Konqi. Each one is a **standee** in colour bands, with a tenon that plugs into a **pedestal**. It follows the same approach as the owner's earlier project `/workspace/3d-halloween-2026` (Nosferatu's Coffin), from which `params.py`, `export.py`, `slicer.py` and `render.py` come.

- **Printer:** Prusa MK4 (Input Shaper firmware) with **one extruder**: no MMU, no INDX. Colours come only from M600 colour changes by layer height, or from separate parts.
- **Slicer profile:** PrusaSlicer "Original Prusa MK4 Input Shaper 0.4 nozzle", "0.20mm STRUCTURAL @MK4IS 0.4", "Prusament PETG @PGIS". 0.2 mm layers (first layer too), 0.45 mm lines.
- **Material:** **Prusament PETG** by default (`--material pla` for Prusament PLA). The owner's filaments: black, white, red, yellow gold, green, orange, violet, grey, blue (`filaments.py`). Map colours only to these.
- **License:** CC BY-SA 4.0. The artwork keeps its own licenses (see `src/linux3d/assets/*/ATTRIBUTION.md`).

## Language

- Write all repository text in **English at B2/C1 level**: README, docstrings, comments. Use clear, short sentences and common words.
- In Markdown, write each paragraph and each list item on **one line** (no hard wraps).
- The owner chats in Italian.

## Environment and commands

- Python 3.14 (3.13 also works), [uv](https://docs.astral.sh/uv/), [build123d](https://github.com/gumyr/build123d) 0.13, shapely 2, svgelements.

```sh
uv sync
uv run pytest                  # ~50 s
uv run linux3d list
uv run linux3d export [FIGURE ...] [--height MM] [--bands a,b] [--set key=value]
uv run linux3d slice [--material pla]   # optional, PrusaSlicer CLI
uv run linux3d render [FIGURE ...] [--gif]
```

- The modules also run on their own: `python -m linux3d.export|slicer|render`.
- PrusaSlicer may have no data directory on a headless machine ("Configuration wasn't found"). Make a folder with `vendor/PrusaResearch.ini` (copied from `/usr/share/PrusaSlicer/profiles/`) and a `PrusaSlicer.ini` with `[presets]` (the three profile names) and `[vendor:PrusaResearch]` / `model:MK4IS = 0.4`, then run `PRUSA_SLICER="prusa-slicer --datadir <folder>" uv run linux3d slice`.

## Layout

| File | Role |
|---|---|
| `src/linux3d/params.py` | Printer grid (`LAYER`, `LINE_W`, `lines()`, `layers()`, `layer_top()`, `snap_up()`), `BASE_T`, `BAND_T`, the slot clearance `CLR_SLOT` |
| `filaments.py` | The owner's filaments (name → hex), nearest-colour mapping in CIELAB, PrusaSlicer material profiles |
| `figures.py` | `Figure` (frozen dataclass): every parameter of a figure and its pedestal. `FIGURES` is the registry; `figure(name, **overrides)` validates (filaments, whole layers, slot depth) |
| `svg.py` | SVG → painted shapes (shapely): transforms, curves, fill rules (exact, with winding numbers), strokes, gradients (average colour), opacity multiplied down the group tree, `visible()` (painter's algorithm) |
| `relief.py` | Figure → colour regions → body, foot, tenon → printable bands → build123d solids; the M600 list |
| `pedestal.py` | Pedestal with slot, 45° top chamfer and raised lettering (bundled Noto Sans Bold) |
| `coupon.py` | Slot gauge: four slots (`SLOT_GAUGE`) and a test tenon |
| `export.py` | STL export with checks; 3MF plates (one per print job, named and coloured, M600s as PrusaSlicer metadata); `plan.json`; assembly preview |
| `slicer.py` | Optional PrusaSlicer CLI run: time and filament, M600 check against `plan.json`, a second slice with automatic supports that must create none, project 3MFs with the full config |
| `render.py` | numpy z-buffer renderer (no OpenGL); `flat_preview()` shows the bands in 2D; `mask()` rasterises a geometry (also used by the tests) |
| `__init__.py` | The `linux3d` command |
| `assets/` | The SVG artwork with `ATTRIBUTION.md` files. Never edit the SVGs; map colours in `figures.py` |
| `tests/` | pytest suite. Keep it green. |

## How a standee is built

- **Bands.** `bands[0]` prints the whole body. Band k (k ≥ 1) covers every region whose colour is band k or higher, so the bands are nested by construction: nothing hangs in the air. A region of a lower colour (Larry's black spots, Gentoo's eye) stays at the top of its own band and looks like a pit.
- **M600.** Band k starts at `base_t + (k - 1) * band_t`. Its M600 is at `layer_top()` of that height.
- **Colour map.** `Figure.colours` maps an SVG element id (`path919`, `path919:stroke`, or `#n` for elements without id) or a colour (`#b8b8b8`) to a filament or to `DROP`. Everything else takes the nearest band colour. Shapes more transparent than `min_opacity` are shading and are left out, unless the map names them. Check every change on `out/render/<name>_flat.png`.
- **Body.** `backing="outline"` grows the drawing by `margin`. If the drawing falls apart into pieces (Plasma's dots), use `hull`, `circle` or `rounded_rect`. `background` fills holes inside the drawing, for drawings that rely on white paper.
- **Foot and tenon.** The body is cut flat at the bottom until the contact is `min_foot` wide (at most `max_cut` of the height). `ground` adds a bar under the feet instead. The tenon is as wide as the contact, `base_t` thick and `tenon_h` long.
- **Cleanup in 2D, not in OCCT.** All booleans run in shapely. Grooves of a lower colour narrower than `MIN_GAP` are widened (long ones) or filled (specks below `SPECK`, and only specks that touch the band: a lone speck would become a raised sliver). Then raised parts thinner than `MIN_STROKE` (85 % of a line) are removed, as the last change to the shape. Finally, cracks of the lower colour narrower than `2 * HAIR` are filled: opening and simplifying move shared edges by a hair, and those cracks showed as thin rings (orange rings around Plasma's dots). A crack always lies against the band, so filling it adds no sliver. `_tidy()` removes zero-width spikes and tiny holes (they gave degenerate faces and a 3MF mesh error); `_clean()` also simplifies.

## Frames

- **2D (standing) frame:** x is centred on the drawing, y points up, the foot is at y = 0, the tenon is below it.
- **Print pose of a standee:** the same x and y on the bed, the front face up (+z), z = 0 on the bed.
- **Assembly frame:** `relief.standing()` turns the standee up: its front faces −y, its back face is at y = 0, the foot at z = 0. The pedestal's top face is at z = 0; `pedestal.print_pose()` lifts it onto the bed.

## Checks after any change

1. Run `uv run pytest`. It covers the fill rules, the colour maps (no unknown keys), uniform scale, nested bands, foot and tenon, tenon/slot fit and collisions, flat faces on the layer grid, M600 heights, raised strokes ≥ 85 % of a line, grooves ≥ one line, lettering strokes, floating islands, valid single solids, watertight STLs, and the 3MF plates.
2. Run `uv run linux3d export`. Every part must print `OK`. Compare the volumes with the previous run.
3. Look at `out/render/*_flat.png` and the renders.
4. If PrusaSlicer is available, run `uv run linux3d slice`: every plate must say `OK`.

## 3MF and PrusaSlicer notes (from the halloween project)

- PrusaSlicer reads `Metadata/Prusa_Slicer_custom_gcode_per_print_z.xml` even from a 3MF without print settings. That is how the M600s travel with the plates. One `<code>` per change, one `<mode>`.
- The `code` and `mode` elements need `bed_idx="0"` (PrusaSlicer 2.9 has multiple beds). Without it the CLI still applies the colour change, but the GUI silently drops it.
- The CLI crashes on `--export-3mf` without a display. So `slicer.py` slices to text G-code, copies the `; prusaslicer_config` block into `Metadata/Slic3r_PE.config` and sets `binary_gcode = 1` again.
- The MK4 profiles build supports only inside support enforcers. `slicer.py` slices once more with `--support-material --support-material-auto --dont-support-bridges`; the result must have no support.
- Never put a standee and a pedestal on the same plate: the standee's M600s would stripe the pedestal.

## build123d gotchas

- **Always pass `dir=(0, 0, 1)` when you extrude a face.** A clockwise polygon has a downward normal and extrudes downwards (all the standees ended up below the bed once).
- `Text` must use the bundled font (`fonts/NotoSans-Bold.ttf`). If the file is missing, it silently uses a system font, so `pedestal.py` raises an error at import instead.
- `Wire.make_polygon` cannot close a ring with near-duplicate points: `relief._wire()` drops them.
- `make_figure`, `band_parts`, `layout` and `make_pedestal` are cached (`functools.cache`, keyed by the frozen `Figure`). Never change a returned part in place; transform it (`Pos(...) * part`) or combine it.
- The tenon reaches 0.05 mm into the body. With an exact touch, shapely kept two polygons and the KDE standee came out as two solids.
- `Shape.clean()` works in place. Copy a cached part first (`Pos() * part`).
- Once OCP is loaded, Python's default text encoding can become ASCII. Always pass `encoding="utf-8"` to `read_text`/`write_text` (the README has emoji).
- svgelements copies a group's `opacity` down to its children, and a child's own value replaces it. `svg.py` multiplies the own values (`values["attributes"]`) down the tree instead. It also folds fill-opacity into a plain colour's alpha already: count it again only for gradients.

## Git

Do not commit or push unless the owner asks. In commit messages, the co-author line is `Co-Authored-By: Claude Opus <noreply@anthropic.com>`, without a version number.
