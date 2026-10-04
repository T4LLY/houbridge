from pathlib import Path


def test_capture_scene_hook_supports_3d_and_uv_viewports_only() -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "houbridge"
        / "houdini"
        / "scripts"
        / "capture"
        / "native"
        / "scene_hook_gate.C"
    ).read_text(encoding="utf-8")

    assert "DM_VIEWPORT_ALL_3D | DM_VIEWPORT_UV" in source
    assert "DM_SceneRenderHook(viewport, DM_VIEWPORT_ALL)" not in source
