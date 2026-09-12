from __future__ import annotations

import base64

from houbridge.process_coordination import ProcessIdentity


def history_session_key(identity: ProcessIdentity) -> str:
    """Return a path-safe, lossless key for one exact Houdini process incarnation."""

    encoded = base64.urlsafe_b64encode(
        identity.process_start_identity.encode("utf-8")
    ).decode("ascii").rstrip("=")
    return f"pid-{identity.pid}-{encoded}"
