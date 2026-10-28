"""Reading SVG: opacity, gradients and paint, as a browser would show them."""

import pytest

from linux3d import svg

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
<defs><linearGradient id="g"><stop offset="0" stop-color="#f00"/>
<stop offset="1" stop-color="#f00"/></linearGradient></defs>
{body}
</svg>"""


def load(tmp_path, body: str) -> dict[str, svg.Shape2D]:
    path = tmp_path / "probe.svg"
    path.write_text(SVG.format(body=body), encoding="utf-8")
    return {s.key: s for s in svg.load(path)}


def test_fill_opacity_counts_once(tmp_path):
    # svgelements already puts fill-opacity into the colour's alpha: no squaring
    shapes = load(tmp_path, '<rect id="r" width="10" height="10" fill="#0f0" '
                            'fill-opacity="0.7"/>')
    assert shapes["r"].opacity == pytest.approx(0.7, abs=0.005)


def test_stroke_opacity_counts_once(tmp_path):
    shapes = load(tmp_path, '<rect id="r" width="10" height="10" fill="none" stroke="#000" '
                            'stroke-width="1" stroke-opacity="0.7"/>')
    assert shapes["r:stroke"].opacity == pytest.approx(0.7, abs=0.005)


def test_gradient_fill_opacity_counts_once(tmp_path):
    shapes = load(tmp_path, '<rect id="r" width="10" height="10" fill="url(#g)" '
                            'fill-opacity="0.7"/>')
    assert shapes["r"].opacity == pytest.approx(0.7)
    assert shapes["r"].colour == "#ff0000"


@pytest.mark.parametrize("ref", ["url(#g)", "url('#g')", 'url("#g")', "url( #g )"])
def test_gradient_reference_forms(tmp_path, ref):
    quote = "'" if '"' in ref else '"'
    shapes = load(tmp_path, f"<rect id={quote}r{quote} width={quote}10{quote} "
                            f"height={quote}10{quote} fill={quote}{ref}{quote}/>")
    assert "r" in shapes and shapes["r"].colour == "#ff0000"


def test_group_opacity_multiplies(tmp_path):
    shapes = load(tmp_path, '<g opacity="0.5"><g style="opacity:0.8">'
                            '<rect id="r" width="10" height="10" opacity="0.9" fill="#f00"/>'
                            '</g></g>')
    assert shapes["r"].opacity == pytest.approx(0.5 * 0.8 * 0.9)


def test_percent_opacity(tmp_path):
    shapes = load(tmp_path, '<rect id="r" width="10" height="10" fill="#00f" '
                            'style="opacity:50%"/>')
    assert shapes["r"].opacity == pytest.approx(0.5)


@pytest.mark.parametrize("text, value", [("1", 1.0), ("0.25", 0.25), ("40%", 0.4),
                                         ("1.5", 1.0), ("-1", 0.0), (None, 1.0)])
def test_fraction(text, value):
    assert svg.fraction(text) == pytest.approx(value)
