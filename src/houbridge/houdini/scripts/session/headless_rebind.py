from __future__ import annotations

import os
from pathlib import Path


bootstrap_dir = Path(os.environ["HOUBRIDGE_SESSION_BOOTSTRAP_DIR"])
marker = bootstrap_dir / "bootstrap.rebind.ready"
staging = marker.with_name(marker.name + ".tmp")
staging.write_text("ready\n", encoding="utf-8")
os.replace(staging, marker)
