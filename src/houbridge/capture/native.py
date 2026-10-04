from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Callable, Mapping
from uuid import uuid4

from houbridge.errors import BridgeError
from houbridge.houdini.installations import subprocess_environment_for
from houbridge.houdini.transport import HoudiniTransport
from houbridge.session.resolver import ResolvedSession
from houbridge.subprocesses import hidden_window_creationflags
from houbridge.temporary_workspace import TemporaryWorkspaceService

from ._injected import write_runpy_runner

_SOURCE_SUFFIXES = {".C", ".h", ".hpp"}
_BUILD_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class NativeCaptureArtifact:
    path: Path
    generation: str
    houdini_build: str


class NativeCaptureBuilder:
    """Build immutable native Capture generations below a persistent cache root."""

    def __init__(
        self,
        cache_root: Path,
        *,
        source_dir: Path | None = None,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        compile_timeout_seconds: float = 120.0,
    ) -> None:
        self._cache_root = cache_root.expanduser()
        if source_dir is None:
            from houbridge.houdini.scripts.capture import native

            source_dir = Path(native.__file__).parent
        self._source_dir = source_dir.resolve()
        self._run = run
        self._compile_timeout_seconds = float(compile_timeout_seconds)

    def ensure(
        self,
        *,
        houdini_build: str,
        hcommand: str | Path,
        environ: Mapping[str, str] | None = None,
    ) -> NativeCaptureArtifact:
        staging: Path | None = None
        try:
            sources = _native_sources(self._source_dir)
            generation = _source_generation(sources)
            build_component = _build_component(houdini_build)
            generation_dir = self._cache_root / f"houdini-{build_component}" / generation
            cached = _read_cached_artifact(generation_dir, generation, houdini_build)
            if cached is not None:
                return cached
            if generation_dir.exists():
                raise BridgeError(
                    "capture_native_cache_invalid",
                    "Native Capture cache generation is incomplete or invalid.",
                    str(generation_dir),
                )

            hcustom = _resolve_hcustom(hcommand)
            environment = subprocess_environment_for(hcustom, environ=environ)
            staging = generation_dir.parent / f".{generation}.{uuid4().hex}.tmp"
            staging.mkdir(parents=True, exist_ok=False)
            source_copy = staging / "src"
            dso_dir = staging / "dso"
            source_copy.mkdir()
            dso_dir.mkdir()
            for source in sources:
                shutil.copyfile(source, source_copy / source.name)

            entry_source = source_copy / "scene_hook_gate.C"
            generated_source = source_copy / f"capture_scene_hook_{generation}.C"
            generated_source.write_bytes(
                f'#define HOUBRIDGE_CAPTURE_GENERATION "{generation}"\n'.encode("ascii")
                + entry_source.read_bytes()
            )
            completed = self._compile(
                hcustom,
                generated_source,
                dso_dir,
                environment,
            )
            if completed.returncode != 0:
                raise BridgeError(
                    "capture_native_compile_failed",
                    "Failed to compile the native Capture component.",
                    _compile_detail(completed),
                )
            dso_path = _find_dso(dso_dir, generated_source.stem)
            metadata = {
                "generation": generation,
                "houdini_build": houdini_build,
                "dso": f"dso/{dso_path.name}",
            }
            (staging / "build.json").write_text(
                json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
                newline="\n",
            )
            generation_dir.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(staging, generation_dir)
            except OSError:
                cached = _read_cached_artifact(generation_dir, generation, houdini_build)
                if cached is None:
                    raise
                return cached
            artifact = _read_cached_artifact(generation_dir, generation, houdini_build)
            if artifact is None:
                raise BridgeError(
                    "capture_native_cache_invalid",
                    "Native Capture cache publication did not produce a usable DSO.",
                )
            return artifact
        except BridgeError:
            raise
        except FileNotFoundError as exc:
            raise BridgeError(
                "capture_native_compiler_not_found",
                "SideFX hcustom was not found for the selected Houdini installation.",
                str(exc),
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise BridgeError(
                "capture_native_compile_timeout",
                f"Native Capture compilation timed out after {self._compile_timeout_seconds:g} seconds.",
                _timeout_detail(exc),
            ) from exc
        except OSError as exc:
            raise BridgeError(
                "capture_native_build_failed",
                "Unable to prepare the native Capture component.",
                f"{type(exc).__name__}: {exc}"[:4096],
            ) from exc
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)

    def _compile(
        self,
        hcustom: Path,
        source: Path,
        dso_dir: Path,
        environment: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        return self._run(
            [str(hcustom), "-i", str(dso_dir), str(source)],
            cwd=str(source.parent),
            env=dict(environment),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=self._compile_timeout_seconds,
            creationflags=hidden_window_creationflags(),
        )


class NativeCaptureGateService:
    """Prove node-free Scene Viewer flipbook reaches the dynamic SceneHook."""

    def __init__(
        self,
        transport: HoudiniTransport,
        builder: NativeCaptureBuilder,
        *,
        workspaces: TemporaryWorkspaceService | None = None,
        script_path: Path | None = None,
    ) -> None:
        self._transport = transport
        self._builder = builder
        self._workspaces = workspaces or TemporaryWorkspaceService()
        if script_path is None:
            from houbridge.houdini.scripts.capture import native_gate

            script_path = Path(native_gate.__file__)
        self._script_path = script_path.resolve()

    def verify(self, session: ResolvedSession) -> NativeCaptureArtifact:
        artifact = self._builder.ensure(
            houdini_build=session.probe.version,
            hcommand=self._transport.executable,
            environ=self._transport.subprocess_environment(),
        )
        workspace = self._workspaces.allocate(prefix="capture-native-gate")
        try:
            result_path = workspace.path_for("result.json")
            request_path = workspace.path_for("request.json")
            request_path.write_text(
                json.dumps(
                    {
                        "dso_path": str(artifact.path),
                        "generation": artifact.generation,
                        "gate_path": str(workspace.path_for("scenehook.gate")),
                        "flipbook_path": str(workspace.path_for("gate.png")),
                        "result_path": str(result_path),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
                newline="\n",
            )
            runner = write_runpy_runner(
                workspace,
                script_path=self._script_path,
                request_path=request_path,
                filename="native_gate.py",
            )
            self._transport.execute_script(session.target, runner)
            _require_gate_success(result_path)
            return artifact
        finally:
            workspace.remove()


def _native_sources(source_dir: Path) -> tuple[Path, ...]:
    sources = tuple(
        sorted(
            (path for path in source_dir.iterdir() if path.is_file() and path.suffix in _SOURCE_SUFFIXES),
            key=lambda path: path.name,
        )
    )
    if not sources:
        raise BridgeError(
            "capture_native_source_missing",
            "Native Capture source files are missing.",
        )
    if not any(path.name == "scene_hook_gate.C" for path in sources):
        raise BridgeError(
            "capture_native_source_missing",
            "Native Capture SceneHook entry source is missing.",
        )
    return sources


def _source_generation(sources: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for source in sources:
        digest.update(source.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(source.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def _build_component(value: str) -> str:
    normalized = _BUILD_COMPONENT_RE.sub("-", value.strip()).strip("-.")
    if not normalized:
        raise BridgeError(
            "capture_native_build_invalid",
            "Houdini build identity is unavailable for native Capture caching.",
        )
    return normalized


def _resolve_hcustom(hcommand: str | Path) -> Path:
    path = Path(hcommand).expanduser()
    suffix = ".exe" if path.suffix.casefold() == ".exe" else ""
    candidate = path.parent / f"hcustom{suffix}"
    if candidate.is_file():
        return candidate.resolve()
    raise FileNotFoundError(candidate)


def _find_dso(directory: Path, stem: str) -> Path:
    for suffix in (".dll", ".so", ".dylib"):
        candidate = directory / f"{stem}{suffix}"
        if candidate.is_file():
            return candidate
    matches = tuple(path for path in directory.glob(f"{stem}.*") if path.is_file())
    if len(matches) == 1:
        return matches[0]
    raise BridgeError(
        "capture_native_compile_failed",
        "Native Capture compilation completed without a uniquely identifiable DSO.",
        str(directory),
    )


def _read_cached_artifact(
    directory: Path,
    generation: str,
    houdini_build: str,
) -> NativeCaptureArtifact | None:
    metadata_path = directory / "build.json"
    try:
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or set(raw) != {"generation", "houdini_build", "dso"}:
        return None
    if raw.get("generation") != generation or raw.get("houdini_build") != houdini_build:
        return None
    relative = raw.get("dso")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        return None
    dso = directory / relative
    if not dso.is_file():
        return None
    return NativeCaptureArtifact(
        path=dso,
        generation=generation,
        houdini_build=houdini_build,
    )


def _compile_detail(completed: subprocess.CompletedProcess[str]) -> str | None:
    parts: list[str] = []
    if completed.stdout:
        parts.append(f"stdout: {_clip(completed.stdout.strip())}")
    if completed.stderr:
        parts.append(f"stderr: {_clip(completed.stderr.strip())}")
    return "\n".join(parts) or None


def _timeout_detail(exc: subprocess.TimeoutExpired) -> str | None:
    parts: list[str] = []
    for label, value in (("stdout", exc.stdout), ("stderr", exc.stderr)):
        if value:
            text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
            parts.append(f"{label}: {_clip(text.strip())}")
    return "\n".join(parts) or None


def _clip(value: str, limit: int = 4096) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "…"


def _require_gate_success(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BridgeError(
            "capture_native_gate_failed",
            "Houdini returned without publishing the native Capture gate result.",
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeError(
            "capture_native_gate_failed",
            "Native Capture gate result is unreadable or invalid JSON.",
            f"{type(exc).__name__}: {exc}"[:4096],
        ) from exc
    if payload == {"ok": True}:
        return
    if not isinstance(payload, dict) or payload.get("ok") is not False:
        raise BridgeError(
            "capture_native_gate_failed",
            "Native Capture gate returned an invalid result envelope.",
        )
    code = payload.get("code")
    message = payload.get("message")
    detail = payload.get("detail")
    raise BridgeError(
        code if isinstance(code, str) and code else "capture_native_gate_failed",
        message if isinstance(message, str) and message else "Native Capture gate failed.",
        detail[:4096] if isinstance(detail, str) and detail else None,
    )
