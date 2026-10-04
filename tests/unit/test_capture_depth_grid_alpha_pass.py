from pathlib import Path


def test_depth_grid_renders_opaque_and_transparent_geometry() -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "houbridge"
        / "houdini"
        / "scripts"
        / "capture"
        / "native"
        / "depth_grid.h"
    ).read_text(encoding="utf-8")

    assert source.count("GR_ALPHA_PASS_ALL") == 1
    assert "GR_ALPHA_PASS_OPAQUE" not in source


def test_depth_grid_uses_displayed_object_filter_without_explicit_models() -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "houbridge"
        / "houdini"
        / "scripts"
        / "capture"
        / "native"
        / "depth_grid.h"
    ).read_text(encoding="utf-8")

    assert (
        "houbridge_displayed_geometry::collect_displayed_objects(viewport, displayed_nodes)"
        in source
    )
    assert "viewport.renderSomeGeometry(" in source
    assert "viewport.renderGeometry(" not in source

    displayed_source = (
        Path(__file__).parents[2]
        / "src"
        / "houbridge"
        / "houdini"
        / "scripts"
        / "capture"
        / "native"
        / "displayed_geometry.h"
    ).read_text(encoding="utf-8")
    assert "viewport.getNumOpaqueObjects()" in displayed_source
    assert "viewport.getNumTransparentObjects()" in displayed_source
    assert "viewport.getNumUnlitObjects()" in displayed_source
    assert "viewport.getNumXRayObjects()" in displayed_source
