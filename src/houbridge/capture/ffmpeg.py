from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from houbridge.errors import BridgeError


def encode_turntable_ffmpeg(frames_dir: Path, *, fps: int, output_path: Path) -> None:
    """Encode transient PNG frames into the only supported turntable artifact."""

    executable = shutil.which("ffmpeg")
    if executable is None:
        raise BridgeError(
            "ffmpeg_not_found",
            "ffmpeg is not available on PATH.",
        )

    command = [
        executable,
        "-y",
        "-framerate",
        str(fps),
        "-start_number",
        "1",
        "-i",
        str(frames_dir / "frame%04d.png"),
        "-c:v",
        "libx264",
        "-vf",
        "pad=ceil(iw/2)*2:ceil(ih/2)*2",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise BridgeError(
            "ffmpeg_execution_failed",
            "Unable to execute ffmpeg.",
            f"{type(exc).__name__}: {exc}",
        ) from exc

    if completed.returncode != 0 or not output_path.is_file():
        detail = (completed.stderr or completed.stdout or "ffmpeg failed.")[:4096]
        raise BridgeError(
            "ffmpeg_encode_failed",
            "ffmpeg failed to encode the turntable video.",
            detail,
        )
