"""The linux3d command: README examples and clear errors."""

import re
import shlex
from pathlib import Path

import pytest

import linux3d
from linux3d import ornament, pedestal, relief

README = Path(__file__).resolve().parents[1] / "README.md"


def readme_commands() -> list[list[str]]:
    """Every `uv run linux3d export|render ...` line in the README's code blocks and in
    the command's own help text."""
    blocks = re.findall(r"```sh\n(.*?)```", README.read_text(encoding="utf-8"), re.DOTALL) + [linux3d.USAGE]
    lines = [re.sub(r"\s#\s.*$", "", line).strip() for b in blocks for line in b.splitlines()]
    return [shlex.split(line)[3:] for line in lines
            if line.startswith(("uv run linux3d export ", "uv run linux3d render "))]


@pytest.mark.parametrize("argv", readme_commands(), ids=" ".join)
def test_readme_examples_work(argv, monkeypatch):
    """Run the documented command up to the geometry (no files written)."""
    seen = []
    monkeypatch.setattr("linux3d.export.export_all", lambda out, figs: seen.extend(figs) or {})
    monkeypatch.setattr("linux3d.render.figure_images",
                        lambda fig, out, with_gif=False: seen.append(fig) or [])
    monkeypatch.setattr("linux3d.render.ornament_images",
                        lambda fig, out, with_gif=False: seen.append(fig) or [])
    with pytest.raises(SystemExit) as e:
        linux3d.main(argv)
        raise SystemExit(0)
    assert e.value.code == 0
    for fig in seen:
        relief.layout(fig)
        pedestal.size(fig)
        ornament.layout(fig)


def test_list_names_the_filaments_to_buy(capsys):
    linux3d.main(["list"])
    lines = {line.split()[0]: line for line in capsys.readouterr().out.splitlines()}
    assert lines["fedora_logo"].endswith("to buy: light_blue")
    assert "to buy" not in lines["konqi"]


def test_lettering_colour_counts_only_with_lettering():
    from linux3d.figures import figure

    assert linux3d._to_buy(figure("tux", text_colour="yellow")) == ["yellow"]
    assert linux3d._to_buy(figure("tux", text_colour="yellow", title="")) == []


def test_readme_has_examples():
    assert len(readme_commands()) >= 5


@pytest.mark.parametrize("argv, message", [
    (["slice", "--material", "abs"], "unknown material"),
    (["export", "larry", "--height"], "--height needs a value"),
    (["export", "larry", "--set", "margin"], "KEY=VALUE"),
    (["export", "larry", "--set", "band_t=0.7"], "layers"),
    (["export", "larry", "--set", "ornament_t=0.8"], "dowel sockets"),
    (["export", "gentoo_logo", "--bands", "violet,grey"], "change the map"),
    (["export", "nobody"], "unknown figure"),
])
def test_clear_errors(argv, message, capsys):
    with pytest.raises(SystemExit) as e:
        linux3d.main(argv)
    assert e.value.code == 2
    assert message in capsys.readouterr().err
