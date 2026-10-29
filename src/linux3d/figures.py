"""Every figure and its parameters: change sizes, colours and the pedestal here.

A figure is a flat standee cut from an SVG drawing. It prints lying down, front face up.
The colours are bands in Z: the first filament prints the whole body, and each M600
switches to the next filament for the next band. A region of colour k is raised to the
top of band k, so from the front you see its colour. A tenon under the figure plugs
into a pedestal, which prints standing up.

The same drawing and bands also make a Christmas tree ornament (ornament.py), at its own
size `ornament_h`.

The drawing only ever scales uniformly (the Gentoo logo guidelines forbid any
distortion), so `height` alone sets the size.
"""

from dataclasses import dataclass, fields, replace
from pathlib import Path

from . import params as P
from .filaments import FILAMENTS
from .params import BAND_T, BASE_T, layers

ASSETS = Path(__file__).resolve().parent / "assets"
DROP = "drop"  # a colour map value: leave this SVG shape out


@dataclass(frozen=True)
class Figure:
    name: str  # file-safe id, used for the output files
    title: str  # lettering on the pedestal ("" = no lettering)
    svg: str  # drawing, relative to assets/
    bands: tuple[str, ...]  # filaments from the bed up; bands[0] prints the whole body
    height: float = 100.0  # height of the drawing when standing (mm); width follows
    # SVG element id, element id + ":stroke", or "#rrggbb" -> filament or DROP.
    # Shapes not listed take the nearest band colour.
    colours: tuple[tuple[str, str], ...] = ()
    min_opacity: float = 0.6  # more transparent shapes are shading: left out
    background: str | None = None  # filament for holes enclosed by the drawing
    backing: str = "outline"  # body shape: outline | hull | circle | rounded_rect
    margin: float = 1.2  # border of the body colour around the drawing (mm)
    corner: float = 8.0  # corner radius of the rounded_rect backing (mm)
    base_t: float = BASE_T  # thickness of the body (band 0), also the tenon
    band_t: float = BAND_T  # every further colour band
    # --- standing up -------------------------------------------------------------------
    min_foot: float = 14.0  # total width of the flat contact at the bottom (mm)
    ground: float = 0.0  # > 0: a bar of the body colour, this high (mm), under the feet
    # when the centre of mass lies beside the foot, add a post of the body colour under
    # the lowest part beyond it (Konqi's raised foot). False: no post; the figure then
    # leans in the slot by up to atan(CLR_SLOT / tenon_h), about 0.7°
    support: bool = True
    max_cut: float = 0.12  # cut at most this fraction of the height to get that foot
    tenon_h: float = 8.0  # how deep the tenon goes into the pedestal
    # --- pedestal (prints standing up) -------------------------------------------------
    pedestal_colour: str = "black"
    text_colour: str | None = None  # lettering colour (M600); None = same as pedestal
    pedestal_h: float = layers(70)  # 14 mm
    pedestal_w: float = 0.0  # 0 = automatic (wider than the figure's foot)
    # 0 = automatic: 45 % of the height, more if the lettering needs it. Either way the
    # figure stands 45 % of the depth from the back edge (pedestal.BACK_SHARE)
    pedestal_d: float = 0.0
    text_h: float = layers(3)  # raised lettering on the top face
    text_size: float = 12.0  # largest font size (mm); smaller if it does not fit
    # --- Christmas tree ornament (ornament.py): two halves, glued back to back --------
    ornament_h: float = 70.0  # height of the drawing (mm); the hanging tab comes on top
    ornament_t: float = layers(6)  # body (band 0) of each half; the colour bands keep band_t
    hole_d: float = 4.0  # hanging hole, for a hook or a ribbon

    @property
    def svg_path(self) -> Path:
        return ASSETS / self.svg

    def colour_map(self) -> dict[str, str]:
        return dict(self.colours)

    def validate(self) -> None:
        if not self.bands:
            raise ValueError(f"{self.name}: bands is empty; give at least one filament")
        names = list(self.bands) + [self.pedestal_colour]
        names += [c for c in (self.background, self.text_colour) if c]
        mapped = [v for _, v in self.colours if v != DROP]
        names += mapped
        unknown = sorted({n for n in names if n not in FILAMENTS})
        if unknown:
            raise ValueError(f"{self.name}: unknown filament(s) {unknown}; "
                             f"choose from {sorted(FILAMENTS)}")
        if len(set(self.bands)) != len(self.bands):
            raise ValueError(f"{self.name}: a filament appears twice in bands {self.bands}")
        for v in [*mapped, self.background]:
            if v and v not in self.bands:
                raise ValueError(f"{self.name}: {v} is mapped but is not one of the bands; "
                                 "add it to bands or change the map (--set colours=...)")
        if self.ground < 0:
            raise ValueError(f"{self.name}: ground must not be negative")
        for key in ("height", "tenon_h", "base_t", "band_t", "pedestal_h", "text_h",
                    "ornament_h", "ornament_t", "hole_d"):
            if getattr(self, key) <= 0:
                raise ValueError(f"{self.name}: {key} must be greater than 0")
        # every band, the pedestal top and the lettering must end on a layer boundary, or
        # the M600 lands one layer late and the slicer rounds the faces away
        for key in ("base_t", "band_t", "pedestal_h", "text_h", "ornament_t"):
            if not P.on_grid(getattr(self, key)):
                raise ValueError(f"{self.name}: {key} = {getattr(self, key)} is not a whole "
                                 f"number of {P.LAYER} mm layers")
        if self.margin < 0:
            raise ValueError(f"{self.name}: margin must not be negative")
        slot = P.snap_up(self.tenon_h + P.SLOT_FLOOR_GAP)
        if slot > self.pedestal_h - P.PEDESTAL_FLOOR:
            raise ValueError(f"{self.name}: the slot ({slot} mm) is too deep for a "
                             f"{self.pedestal_h} mm pedestal: make pedestal_h at least "
                             f"{P.snap_up(slot + P.PEDESTAL_FLOOR)} or tenon_h smaller")
        if self.ornament_t < P.MIN_ORNAMENT_T - 1e-9:
            raise ValueError(f"{self.name}: ornament_t = {self.ornament_t} leaves too little "
                             f"above the dowel sockets; use at least {P.MIN_ORNAMENT_T}")
        if self.backing not in ("outline", "hull", "circle", "rounded_rect"):
            raise ValueError(f"{self.name}: unknown backing {self.backing!r}")
        if not self.svg_path.is_file():
            raise FileNotFoundError(self.svg_path)


FIGURES = {f.name: f for f in [
    Figure(
        name="gentoo_logo", title="gentoo", svg="gentoo/Gentoo-logo-peach-plain.svg",
        bands=("violet", "white"),
        # the outer bevel is violet, the face of the "g" white, the eye stays violet;
        # the two shadow shapes and the blurred highlight are below min_opacity
        colours=(("path919", "violet"), ("path2165", "white"), ("path2166", "white"),
                 ("path2167", "violet")),
        # the "g" stands on its lower left lobe, 14 mm beside its centre of mass. A post
        # or a plinth would change the logo's outline, which the Gentoo guidelines
        # forbid: it leans in the slot instead, by 0.7° at most (about 1 mm at the top)
        support=False,
        text_colour="white", pedestal_colour="violet",
    ),
    Figure(
        name="larry", title="Larry", svg="gentoo/Larry-the-cow-full.svg",
        bands=("black", "white"), height=90.0,
        text_colour="white",
    ),
    Figure(
        name="kde_logo", title="KDE", svg="kde/kdeapp.svg",
        bands=("blue", "white"), margin=0.0,  # the rounded square is the body
        text_colour="white", pedestal_colour="blue",
    ),
    Figure(
        name="plasma_logo", title="Plasma", svg="kde/start-here-kde.svg",
        bands=("white", "black", "orange", "green", "blue"),
        backing="circle", margin=6.0, height=90.0,
        text_colour="white",
    ),
    Figure(
        name="konqi", title="Konqi", svg="kde/Konqi.svg",
        # a black body gives the cartoon outline: the dark green and brown outlines of
        # the drawing become black grooves, and the colours rise above them
        bands=("black", "green", "white", "red", "orange"),
        colours=(("#b8b8b8", DROP),  # grey shading and the ground shadow
                 ("#49801d", "black"), ("#906119", "black"), ("#905f16", "black"),
                 ("#bbeb8c", "white")),  # the light belly
        # Konqi stands on one foot, 11 mm beside its centre of mass: `support` puts a
        # post under the raised foot (6.4 mm up), and the tenon reaches under both feet
        height=120.0, min_foot=10.0, text_colour="green",
    ),
    Figure(
        name="tux", title="Tux", svg="tux/penguin-flat.svg",
        bands=("black", "white", "gold"),  # Simon Budig's three-colour Tux
        # the thin highlight lines on the wings and over the eyes are thinner than a
        # line: at 100 mm they print in pieces, at 70 mm not at all. Leave them out, so
        # Tux looks the same at any size
        colours=tuple((key, DROP) for key in ("#28", "#29", "#34", "#35", "#36")),
        text_colour="gold",
    ),
    Figure(
        name="gnu", title="GNU", svg="gnu/Heckert_GNU_white.svg",
        bands=("black", "white"),
        background="white",  # some gaps between the strands of fur go right through
        text_colour="white",
    ),
    Figure(
        name="debian_logo", title="Debian", svg="debian/openlogo-nd.svg",
        bands=("white", "red"),
        backing="circle", margin=4.0, height=90.0,  # the swirl has loose brush flecks
        text_colour="white", pedestal_colour="red",
    ),
    Figure(
        name="arch_logo", title="Arch Linux", svg="arch/archlinux-logo-only.svg",
        bands=("white", "blue"),
        # the logo without its ™ sign (the owner's choice): the ™ is 4 mm tall beside the
        # A and prints whole only from about 140 mm, where the gaps inside the M are
        # one line wide
        colours=(("path3940", DROP), ("path3942", DROP)),
        text_colour="white", pedestal_colour="blue",
    ),
    Figure(
        name="fedora_logo", title="Fedora", svg="fedora/fedora_dark-background.svg",
        bands=("light_blue", "white"),  # the official colours: the owner buys light_blue
        # the logo mark only: the "fedora" wordmark is left out
        colours=tuple((key, DROP) for key in ("path1946", "path1948", "path1950",
                                              "path1952", "path1956", "path1958")),
        margin=0.0,  # the bubble is the body
        text_colour="white", pedestal_colour="light_blue",
    ),
    Figure(
        name="katie", title="Katie", svg="kde/katie.svg",  # traced: tools/trace_katie.py
        # the official colours of her 2026 design (the owner buys the three new ones),
        # except her amber (#ffaf2f), which prints in the owner's yellow gold. As for
        # Konqi, a black body gives the cartoon outline: the green, orange and grey
        # outlines of the drawing become black, and so do the eye and the mouth. Gold
        # comes last: the amber shading tapers to a point along the edges of the yellow
        # parts, and below the yellow those tips would be grooves narrower than a line
        bands=("black", "light_green", "bright_green", "white", "yellow", "gold"),
        colours=(("#3fca3b", "black"), ("#db862c", "black"), ("#b8b8b8", "black"),
                 ("#434343", "black"), ("#e3311c", "black"), ("#ef551a", "black"),
                 ("#dbdbdb", "white"),  # shading on the white parts
                 ("#aaebb1", "bright_green"), ("#cef2a0", "light_green")),  # highlights
        # she stands on one small shoe and lifts the other foot: a 14 mm foot would cut
        # her leg off at the shin, so the foot is narrower and a post goes under the
        # lifted foot (18.6 mm up). The tenon reaches under both
        height=120.0, min_foot=8.0, text_colour="gold",
    ),
]}


def figure(name: str, **overrides) -> Figure:
    """A figure from the registry, with some parameters changed."""
    if name not in FIGURES:
        raise KeyError(f"unknown figure {name!r}; choose from {sorted(FIGURES)}")
    fig = replace(FIGURES[name], **overrides) if overrides else FIGURES[name]
    fig.validate()
    return fig


def parse_value(fig: Figure, key: str, text: str):
    """Turn a command line value into the type of the Figure field `key`."""
    kinds = {f.name: f.type for f in fields(Figure)}
    if key not in kinds:
        raise KeyError(f"unknown parameter {key!r}; choose from {sorted(kinds)}")
    current = getattr(fig, key)
    if key == "bands":  # black,white
        return tuple(s.strip() for s in text.split(",") if s.strip())
    if key == "colours":  # path919=violet,#b8b8b8=drop
        pairs = [item.partition("=") for item in text.split(",") if item.strip()]
        if any(not sep or not v.strip() for _, sep, v in pairs):
            raise ValueError(f"colours: write KEY=FILAMENT pairs separated by commas: {text!r}")
        return tuple((k.strip(), v.strip()) for k, _, v in pairs)
    if isinstance(current, bool):
        return text.lower() in ("1", "true", "yes")
    if isinstance(current, float):
        return float(text)
    if text.lower() in ("none", ""):
        return None
    return text
