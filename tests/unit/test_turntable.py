from __future__ import annotations

import json
import struct
import zlib
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from houbridge.capture.artifacts import CaptureArtifactPublisher
from houbridge.capture.ffmpeg import encode_turntable_ffmpeg
from houbridge.capture.turntable import TurntableService, parse_turntable_pivot
from houbridge.config import ScreenshotConfig
from houbridge.errors import BridgeError
from houbridge.houdini.transport import HoudiniTarget
from houbridge.temporary_artifact import TemporaryArtifactService
from houbridge.temporary_workspace import TemporaryWorkspaceService


def _png(width: int, height: int) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return (
            struct.pack(">I", len(data))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    raw = b"\x00" + b"\x00\x00\x00\x00" * width
    return (
        signature
        + chunk(b"IHDR", ihdr_data)
        + chunk(b"IDAT", zlib.compress(raw * height))
        + chunk(b"IEND", b"")
    )


class _Session(SimpleNamespace):
    target = HoudiniTarget("127.0.0.1", 49152)


class _TurntableTransport:
    def __init__(self, *, width: int = 65, height: int = 33, fail: bool = False) -> None:
        self.width = width
        self.height = height
        self.fail = fail
        self.requests: list[dict[str, object]] = []

    def execute_script(self, _target, runner: Path):
        workspace = runner.parent
        request = json.loads((workspace / "request.json").read_text(encoding="utf-8"))
        self.requests.append(request)
        if not self.fail:
            frames_dir = Path(request["frames_dir"])
            for index in range(int(request["frames"])):
                (frames_dir / f"frame{index + 1:04d}.png").write_bytes(
                    _png(self.width, self.height)
                )
            payload = {"ok": True}
        else:
            payload = {"ok": False, "message": "capture failed", "detail": "trace"}
        Path(request["result_path"]).write_text(
            json.dumps(payload, separators=(",", ":")),
            encoding="utf-8",
        )


def _service(tmp_path: Path, transport=None) -> tuple[TurntableService, TemporaryArtifactService]:
    artifacts = TemporaryArtifactService(temp_root=tmp_path / "os-temp")
    publisher = CaptureArtifactPublisher(
        artifacts,
        1,
        now_timestamp=lambda: 10_000.0,
        now_datetime=lambda: datetime(2026, 9, 11, 20, 15),
    )
    service = TurntableService(
        transport or _TurntableTransport(),
        ScreenshotConfig(retention_hours=1, max_width=2048, max_height=2048),
        publisher,
        workspaces=TemporaryWorkspaceService(temp_root=tmp_path / "os-temp"),
    )
    return service, artifacts


def test_turntable_defaults_capture_160_frames_and_publish_mp4_only(tmp_path: Path, monkeypatch) -> None:
    transport = _TurntableTransport()
    service, artifacts = _service(tmp_path, transport)

    def encode(frames_dir: Path, *, fps: int, output_path: Path) -> None:
        assert fps == 30
        assert len(list(frames_dir.glob("frame*.png"))) == 160
        output_path.write_bytes(b"mp4")

    monkeypatch.setattr("houbridge.capture.turntable.encode_turntable_ffmpeg", encode)

    result = service.capture(_Session())

    assert set(result) == {"path"}
    path = Path(result["path"])
    assert path.name == "turntable20260911-2015-001.mp4"
    assert path.read_bytes() == b"mp4"
    assert transport.requests[0]["frames"] == 160
    assert transport.requests[0]["pivot"] == [0.0, 0.0, 0.0]
    assert transport.requests[0]["distance"] is None
    capture_dir = artifacts.root / "capture"
    assert [item.name for item in capture_dir.iterdir()] == [path.name]
    assert not any(item.suffix == ".png" for item in capture_dir.iterdir())


def test_explicit_distance_and_pivot_are_forwarded_without_changing_direction_contract(
    tmp_path: Path, monkeypatch
) -> None:
    transport = _TurntableTransport()
    service, _artifacts = _service(tmp_path, transport)
    monkeypatch.setattr(
        "houbridge.capture.turntable.encode_turntable_ffmpeg",
        lambda _frames_dir, *, fps, output_path: output_path.write_bytes(b"mp4"),
    )

    service.capture(
        _Session(),
        frames=2,
        pivot=(1.0, -2.0, 3.5),
        distance=5.0,
    )

    request = transport.requests[0]
    assert request["pivot"] == [1.0, -2.0, 3.5]
    assert request["distance"] == 5.0


def test_turntable_rejects_invalid_pivot_distance_and_turntable_incompatible_preset_before_transport(
    tmp_path: Path,
) -> None:
    transport = _TurntableTransport()
    service, _artifacts = _service(tmp_path, transport)
    preset = tmp_path / "preset.json"
    preset.write_text('{"view":"front"}', encoding="utf-8")

    with pytest.raises(BridgeError) as pivot:
        parse_turntable_pivot("1,2")
    with pytest.raises(BridgeError) as distance:
        service.capture(_Session(), frames=2, distance=float("nan"))
    with pytest.raises(BridgeError) as invalid_preset:
        service.capture(_Session(), frames=2, preset_path=preset)

    assert pivot.value.code == "invalid_turntable_pivot"
    assert distance.value.code == "invalid_turntable_distance"
    assert invalid_preset.value.code == "turntable_preset_invalid"
    assert transport.requests == []


def test_ffmpeg_is_required_after_frame_capture_and_missing_ffmpeg_publishes_nothing(
    tmp_path: Path, monkeypatch
) -> None:
    transport = _TurntableTransport()
    service, artifacts = _service(tmp_path, transport)
    monkeypatch.setattr("houbridge.capture.ffmpeg.shutil.which", lambda _name: None)

    with pytest.raises(BridgeError) as caught:
        service.capture(_Session(), frames=2)

    assert caught.value.code == "ffmpeg_not_found"
    assert len(transport.requests) == 1
    capture_dir = artifacts.root / "capture"
    assert not capture_dir.exists() or list(capture_dir.iterdir()) == []


def test_ffmpeg_profile_uses_h264_yuv420p_and_even_dimension_padding(tmp_path: Path, monkeypatch) -> None:
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    output = tmp_path / "turntable.mp4"
    commands = []

    monkeypatch.setattr("houbridge.capture.ffmpeg.shutil.which", lambda _name: "/usr/bin/ffmpeg")

    def run(command, **kwargs):
        commands.append((command, kwargs))
        output.write_bytes(b"mp4")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("houbridge.capture.ffmpeg.subprocess.run", run)

    encode_turntable_ffmpeg(frames_dir, fps=24, output_path=output)

    command, kwargs = commands[0]
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"
    assert command[command.index("-vf") + 1] == "pad=ceil(iw/2)*2:ceil(ih/2)*2"
    assert command[command.index("-framerate") + 1] == "24"
    assert command[command.index("-start_number") + 1] == "1"
    assert kwargs == {"capture_output": True, "text": True, "check": False}


def test_capture_or_encoding_failure_never_publishes_frames_or_video(tmp_path: Path, monkeypatch) -> None:
    service, artifacts = _service(tmp_path, _TurntableTransport(fail=True))

    with pytest.raises(BridgeError) as capture_failure:
        service.capture(_Session(), frames=2)
    assert capture_failure.value.code == "turntable_failed"

    service, _artifacts = _service(tmp_path, _TurntableTransport())

    def fail_encode(_frames_dir: Path, *, fps: int, output_path: Path) -> None:
        raise BridgeError("ffmpeg_encode_failed", "failed")

    monkeypatch.setattr("houbridge.capture.turntable.encode_turntable_ffmpeg", fail_encode)
    with pytest.raises(BridgeError) as encode_failure:
        service.capture(_Session(), frames=2)
    assert encode_failure.value.code == "ffmpeg_encode_failed"

    capture_dir = artifacts.root / "capture"
    assert not capture_dir.exists() or list(capture_dir.iterdir()) == []


def test_turntable_injected_code_uses_shared_runtime_clockwise_orbit_and_distance_rule() -> None:
    from houbridge.houdini.scripts.capture import turntable

    source = Path(turntable.__file__).read_text(encoding="utf-8")
    assert 'runtime["clone_scene_viewer"]' in source
    assert 'runtime["flipbook_png"]' in source
    assert 'runtime["apply_preset"]' in source
    assert "angle = -360.0 * float(index) / float(frames)" in source
    assert "offset = hou.Vector3(source_world_position) - pivot" in source
    assert "if distance_value is not None:" in source
    assert "float(distance_value) / offset.length()" in source
    assert "if offset.length() <= 1e-9:" in source
    assert "frame_camera.setPivot(tuple(pivot))" in source
    assert "source_scene.set" not in source
