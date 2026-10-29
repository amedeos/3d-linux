# 3d-linux: Linux logos and mascots for your desk and your Christmas tree 🐧🎄

Parametric, printable figures of Linux logos and mascots: the **Gentoo** logo, **Larry the Cow**, the **KDE** logo, the **Plasma** logo and **Konqi**. Each one is a colourful standee that stands upright on a pedestal with its name on it, and also a **Christmas tree ornament** with the drawing on both sides.

Everything is written in Python with [build123d](https://github.com/gumyr/build123d). The shapes come from the official SVG artwork, and every size, colour and clearance is a parameter.

## How it works

- **A standee in colour bands.** The figure prints lying flat, front face up. The first filament prints the whole body. After that, each colour change (M600) adds one band, and every region of that colour rises to the top of its band. From the front you see the drawing in colour. You need **one extruder only**: no MMU and no INDX.
- **A tenon and a pedestal.** A flat foot and a tenon are added under the figure. The pedestal prints standing up and has a slot for the tenon. Its name is raised on the top face, in a second colour.
- **The shapes come from SVG.** `svg.py` reads the drawing: fills, strokes, gradients, the fill rules and the paint order. Every colour of the drawing goes to the nearest filament you have (or to the one you choose). The drawing only ever scales uniformly, so the logos keep their proportions.
- **Made for the slicer grid.** Every band is a whole number of 0.2 mm layers. Raised details are at least 85 % of a line wide, and the grooves between them (Larry's black outlines, for example) are at least one line wide, so nothing disappears in the slicer.

## The figures

| Figure | Height | Colour bands (from the bed up) | Pedestal | Ornament |
|---|---|---|---|---|
| `gentoo_logo` | 100 mm | violet → white | violet, white lettering | 70 mm, back mirrored |
| `larry` | 90 mm | black → white | black, white lettering | 70 mm, back mirrored |
| `kde_logo` | 100 mm | blue → white | blue, white lettering | 70 mm, same on both sides |
| `plasma_logo` | 90 mm | white → black → orange → green → blue | black, white lettering | 70 mm, same on both sides |
| `konqi` | 120 mm | black → green → white → red → orange | black, green lettering | 70 mm, back mirrored |

The height is the height of the drawing. The ornaments use the same colour bands as the standees.

The filaments are the ones on the author's shelf (Prusament PETG): black, white, red, yellow gold, green, orange, violet, grey and blue. Change them in `src/linux3d/filaments.py`.

## Requirements

- [uv](https://docs.astral.sh/uv/) and Python 3.14 (3.13 also works)
- `uv sync` installs build123d, shapely, svgelements, trimesh and pillow
- Optional: PrusaSlicer 2.9 for `linux3d slice`

```sh
uv sync
uv run pytest                     # ~140 s: SVG reading, bands, layers, fit, printability, ornaments, 3MF, CLI
uv run linux3d list               # the figures and their colour bands
uv run linux3d export             # STL files and 3MF plates in out/standees and out/ornaments
uv run linux3d slice              # optional, needs PrusaSlicer: times, M600 check, projects
uv run linux3d render             # PNG previews in out/*/render (add --gif for a turning GIF)
```

`export` exits with status 1 if a part has a problem. Every command makes both the standees and the ornaments. The output has one folder per kind, with the same layout inside:

| Folder | Contents |
|---|---|
| `out/standees/` | standees, pedestals and the slot gauge |
| `out/ornaments/` | Christmas tree ornaments (two halves each) |
| `…/stl/` | one STL per part, already in its print position |
| `…/3mf/` | one 3MF plate per print job, with the colour changes; `plan.json`; `assembly_preview.3mf` (view only) |
| `…/3mf/projects/` | PrusaSlicer projects, written by `slice` |
| `…/render/` | PNG previews, written by `render` |

## Change the parameters

Every figure is a `Figure` in `src/linux3d/figures.py`. You can change any field there, or from the command line for one run:

```sh
uv run linux3d export larry --height 120                 # a bigger Larry
uv run linux3d export larry --bands black,gold           # other filaments
uv run linux3d export konqi --set text_colour=none       # pedestal in one colour
uv run linux3d export kde_logo --set pedestal_h=12 --set margin=2
uv run linux3d export larry --set ornament_h=80          # a bigger Larry ornament
uv run linux3d export konqi --set hole_d=5               # a larger hole for a ribbon
uv run linux3d export gentoo_logo --bands violet,grey --set colours=path919=violet,path2165=grey,path2166=grey,path2167=violet
uv run linux3d slice --material pla                      # slice with Prusament PLA
```

Useful parameters: `height`, `bands`, `support` (a post when the figure would lean, see Stability), `colours` (SVG element id or colour → filament, e.g. `--set colours=path919=violet,#b8b8b8=drop`), `margin` (border around the drawing), `backing` (`outline`, `hull`, `circle` or `rounded_rect`), `base_t` and `band_t` (band thickness), `min_foot` and `tenon_h`, `pedestal_colour`, `text_colour`, `pedestal_h`, `pedestal_w`, `pedestal_d`, `title`. For the ornaments: `ornament_h` (height of the drawing), `ornament_t` (body of each half) and `hole_d` (hanging hole). `--height` changes only the standee. Both halves of an ornament must fit side by side on the bed, so `ornament_h` goes up to about 100 mm for the Plasma logo and 110 mm for Larry; beyond that, `export` stops with an error before it writes any file.

Thicknesses and heights (`base_t`, `band_t`, `pedestal_h`, `text_h`, `ornament_t`) must be whole numbers of 0.2 mm layers; the command refuses other values, because the colour change would land one layer late.

To add your own figure, put an SVG into `src/linux3d/assets/` and add a `Figure` to the list. Then check the colour mapping in `out/standees/render/<name>_flat.png` and `out/ornaments/render/<name>_flat.png`.

## Printing

Prusa MK4 (Input Shaper firmware), **Prusament PETG** (PLA also works), 0.4 mm nozzle, **0.20mm STRUCTURAL** profile, **no supports**. PrusaSlicer confirms this: even with automatic supports turned on, it does not generate any. Use the textured or satin sheet: PETG sticks too much to the smooth PEI sheet.

There are three kinds of files, in `out/standees/` and in `out/ornaments/`. Use whichever you like:

- **`3mf/projects/*.3mf` — easiest.** PrusaSlicer projects with the MK4 + 0.20mm STRUCTURAL + Prusament PETG settings already loaded, and every colour change already set.
- **`3mf/*.3mf`** — the same plates without print settings. They also include the colour changes. Use them with any printer profile.
- **`stl/*.stl`** — one file per part, already in its print position. Add the colour changes yourself.

The standees (`out/standees/`):

| Plate (3MF) | Colour changes (M600) | Time* | Filament* |
|---|---|---|---|
| `gentoo_logo_standee_violet-white` | white at 2.60 mm | 36 min | 19 g |
| `gentoo_logo_pedestal_violet-white` | white at 14.20 mm | 42 min | 20 g |
| `larry_standee_black-white` | white at 2.60 mm | 33 min | 13 g |
| `larry_pedestal_black-white` | white at 14.20 mm | 37 min | 17 g |
| `kde_logo_standee_blue-white` | white at 2.60 mm | 51 min | 28 g |
| `kde_logo_pedestal_blue-white` | white at 14.20 mm | 50 min | 24 g |
| `plasma_logo_standee_white-black-orange-green-blue` | black 2.60, orange 3.40, green 4.20, blue 5.00 mm | 44 min | 24 g |
| `plasma_logo_pedestal_black-white` | white at 14.20 mm | 37 min | 18 g |
| `konqi_standee_black-green-white-red-orange` | green 2.60, white 3.40, red 4.20, orange 5.00 mm | 57 min | 20 g |
| `konqi_pedestal_black-green` | green at 14.20 mm | 51 min | 25 g |
| `coupon_slot_gauge` | none | 22 min | 7 g |

The ornaments (`out/ornaments/`), both halves on one plate:

| Plate (3MF) | Colour changes (M600) | Time* | Filament* |
|---|---|---|---|
| `gentoo_logo_ornament_violet-white` | white at 1.40 mm | 31 min | 15 g |
| `larry_ornament_black-white` | white at 1.40 mm | 30 min | 10 g |
| `kde_logo_ornament_blue-white` | white at 1.40 mm | 36 min | 17 g |
| `plasma_logo_ornament_white-black-orange-green-blue` | black 1.40, orange 2.20, green 3.00, blue 3.80 mm | 40 min | 21 g |
| `konqi_ornament_black-green-white-red-orange` | green 1.40, white 2.20, red 3.00, orange 3.80 mm | 39 min | 11 g |

\* PrusaSlicer 2.9.6 estimates (Prusament PETG, 0.20mm STRUCTURAL), not counting the time for the filament changes.

**Each standee and its pedestal are separate plates.** The standee's colour changes would put stripes on the pedestal walls, so never print them together.

### The colour changes

The 3MF files already contain them. With the STL files, add them yourself: open the preview, move the vertical slider to the layer and click the **+**.

- The body is 2.4 mm thick (12 layers). The first colour change comes before the layer that ends at 2.60 mm.
- Every further band is 0.8 mm thick (4 layers). If a light colour (white above all) looks greyish over the dark one on your first print, make the bands thicker: `--set band_t=1.2` (6 layers).
- The pedestal is 14 mm high. Its lettering starts with an M600 before the layer that ends at 14.20 mm.
- The body of an ornament half is 1.2 mm thick (6 layers), so its first colour change comes before the layer that ends at 1.40 mm.

### Stability

The tenon in the slot holds the figure; the pedestal keeps the whole thing on its feet. Two rules keep the figures steady:

- **The centre of mass lies over the foot.** Otherwise the tenon carries the whole weight on one side, and the figure leans in the slot until the tenon meets the wall: by up to 0.7° with the default clearance (about 1 mm at the top). With `support` (on by default), the program computes the centre of mass and, if it lies less than 3 mm inside the foot, adds a post in the body colour under the lowest part beyond it. Konqi stands on one foot in its drawing, so it gets a black post under its raised foot, 7.4 mm high. This works at any `--height`; if no part of the figure comes low enough, `export` stops with an error.
- **The Gentoo logo is the exception.** The "g" stands on its lower left lobe, 15 mm beside its centre of mass, but a post would change the logo's outline. So it has `support=False` and leans by up to 0.7°. A tighter slot from the slot gauge makes that smaller. `export` prints a note for every figure that gets a post or that leans.
- **The pedestal is deep, and the figure stands near its middle.** The automatic depth is 45 % of the figure height (more if the lettering needs it), and the figure stands 45 % of the depth from the back edge, also with your own `pedestal_d`. Every assembly must tilt by at least 26° (Plasma) to 38° (Konqi) before it falls over. It still weighs only 30 to 51 g, so a push of 6 to 10 grams-force at the top tips it over backwards.

`tests/test_relief.py` checks the rules for every figure, at heights of 60, 100 and 150 mm.

### The fit of the tenon

The slot is 0.10 mm wider than the tenon on each side. This worked well in PETG on an MK4. If your tenon is too loose or too tight, print the **slot gauge** first (about 20 minutes): a block with four slots (0.05, 0.10, 0.15 and 0.20 mm per side, marked with 1 to 4 dots) and a test tenon. Use the slot that holds firmly but still goes in by hand, and set `CLR_SLOT` in `src/linux3d/params.py`.

## Christmas tree ornaments

Every figure is also an ornament for the Christmas tree, 70 mm high (plus the hanging tab), with the drawing on both sides.

- **Two halves, glued back to back.** With one extruder, the face on the bed comes out in one colour. So each ornament is two halves, printed together on one plate with the same colour changes. Glue them with their flat bed faces together.
- **The back.** Turned over, the back half must have the mirror image of the front's outline, or the two do not line up. If the outline is symmetric (the KDE square, the Plasma disc), the back half is simply a copy of the front, and the drawing reads the right way round from behind too. Otherwise (Gentoo, Larry, Konqi) the back half is the mirror image: from behind, the drawing looks as if you saw it through the ornament.
- **It hangs upright.** A tab with a 4 mm hole (for an ornament hook or a thin ribbon) sits on top, straight above the centre of mass, so the ornament does not hang crooked. The tab is in the body colour and lies outside the drawing, which keeps its shape and colours. `export` prints how far each ornament hangs off upright (0.01° at most).
- **Dowels line the halves up.** The glued face of each half has two small blind holes (2 mm wide, 0.6 mm deep). Cut two pieces of 1.75 mm filament, about 1 mm long, and put them into the holes of one half before you glue: they hold the two halves in place while the glue sets.
- **Glue.** For PETG, use cyanoacrylate (super glue) or a two-part epoxy, a thin layer, and press the halves together for a minute. A toothpick through both hanging holes helps to line them up too.
- Each half is thin (1.2 mm body + 0.8 mm per colour band), so a glued ornament weighs only 10 to 21 g.

## Artwork, trademarks and license

The models use official artwork. See the `ATTRIBUTION.md` files in `src/linux3d/assets/`:

- the Gentoo logo and Larry the Cow: CC BY-SA 2.5 (Gentoo Foundation, Lennart Andre Rolland, Matteo Pescarin, Ethan Dunham);
- the KDE and Plasma logos: Breeze icons, LGPL-3.0-or-later;
- Konqi: designed by Tyson Tan, SVG by Franco Perez, CC BY-SA 4.0.

Gentoo is a trademark of the Gentoo Foundation, Inc. KDE® is a registered trademark of KDE e.V. This project is not affiliated with either of them. Please do not sell prints of the logos without their permission.

The pedestal lettering uses Noto Sans Bold (SIL Open Font License 1.1).

This repository is under **CC BY-SA 4.0** (see `LICENSE`).
