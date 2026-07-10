from pathlib import Path

import pytest
from PIL import Image

from claimtrace.api import init_package
from claimtrace.importers.image import inspect_image


def test_raster_and_svg_images_are_verified(tmp_path: Path):
    png = tmp_path / "panel.png"
    Image.new("RGB", (3, 2), color=(10, 20, 30)).save(png, format="PNG")
    svg = tmp_path / "panel.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 80"><rect width="120" height="80"/></svg>',
        encoding="utf-8",
    )

    assert inspect_image(png)["dimensions"] == (3, 2)
    assert inspect_image(svg)["dimensions"] == (120, 80)


def test_invalid_render_is_rejected_before_package_creation(tmp_path: Path):
    invalid = tmp_path / "panel.png"
    invalid.write_bytes(b"not an image")
    output = tmp_path / "pkg"

    with pytest.raises(ValueError, match="cannot be decoded"):
        init_package(image=invalid, out=output)

    assert not output.exists()


def test_svg_document_type_is_rejected(tmp_path: Path):
    svg = tmp_path / "unsafe.svg"
    svg.write_text(
        '<!DOCTYPE svg [<!ENTITY example "value">]><svg xmlns="http://www.w3.org/2000/svg"/>',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="safe, well-formed"):
        inspect_image(svg)


def test_svg_absolute_units_are_converted_to_css_pixels(tmp_path: Path):
    svg = tmp_path / "units.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1in" height="25.4mm"/>',
        encoding="utf-8",
    )

    assert inspect_image(svg)["dimensions"] == (96, 96)


def test_tiny_positive_svg_dimensions_do_not_round_to_zero(tmp_path: Path):
    svg = tmp_path / "tiny.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 0.1 0.1"/>',
        encoding="utf-8",
    )

    assert inspect_image(svg)["dimensions"] == (1, 1)
