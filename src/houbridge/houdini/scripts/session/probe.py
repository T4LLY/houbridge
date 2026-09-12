from __future__ import annotations

import json
import os
from pathlib import Path


def _license_name(category: object) -> str:
    name = getattr(category, "name", None)
    if callable(name):
        return str(name())
    if isinstance(name, str):
        return name
    return str(category)


def _open_ports(hou: object) -> list[int]:
    output, _errors = hou.hscript("openport")  # type: ignore[attr-defined]
    ports: list[int] = []
    for token in output.replace("\r", " ").replace("\n", " ").split():
        if token.isascii() and token.isdigit():
            port = int(token)
            if 1 <= port <= 65535:
                ports.append(port)
    return sorted(set(ports))


def main() -> None:
    import hou

    try:
        is_new_file = bool(hou.hipFile.isNewFile())
        hip_file = None if is_new_file else str(hou.hipFile.path())
    except Exception:
        hip_file = None

    payload = {
        "pid": os.getpid(),
        "version": str(hou.applicationVersionString()),
        "license": _license_name(hou.licenseCategory()),
        "file": hip_file or None,
        "headless": not bool(hou.isUIAvailable()),
        "open_ports": _open_ports(hou),
    }
    result_path = Path(__file__).with_suffix(".json")
    staging = result_path.with_suffix(".json.tmp")
    staging.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    staging.replace(result_path)


if __name__ == "__main__":
    main()
