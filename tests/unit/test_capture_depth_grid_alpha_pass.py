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

    assert source.count("GR_ALPHA_PASS_ALL") == 2
    assert "GR_ALPHA_PASS_OPAQUE" not in source
