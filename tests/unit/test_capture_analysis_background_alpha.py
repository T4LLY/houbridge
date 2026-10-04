from pathlib import Path


def test_geometry_analysis_passes_clear_to_opaque_black() -> None:
    native_dir = (
        Path(__file__).parents[2]
        / "src"
        / "houbridge"
        / "houdini"
        / "scripts"
        / "capture"
        / "native"
    )

    opaque_black = "setClearColor(UT_Vector4F(0.0f, 0.0f, 0.0f, 1.0f))"
    for name in ("normal.h", "object_id.h", "curvature.h"):
        source = (native_dir / name).read_text(encoding="utf-8")
        assert opaque_black in source
        assert "setClearColor(UT_Vector4F(0.0f, 0.0f, 0.0f, 0.0f))" not in source
