"""Version and build identification.

``__version__`` stays a plain numeric string: the updater compares it against
GitHub release tags with ``int(x) for x in v.split(".")``, so any suffix there
would break update notifications. Build provenance lives in
``__version_label__`` instead, which is what the web UI and the bot's
help/changelog text display.
"""

import os
import subprocess
from pathlib import Path

__version__ = "1.31.1"

_SHA_LEN = 7


def _git_build_id() -> str:
    """Return ``<short-sha>[-dirty]`` for the checkout, or ``""`` when unavailable."""
    root = Path(__file__).resolve().parent
    try:
        sha = subprocess.run(
            ["git", "rev-parse", f"--short={_SHA_LEN}", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=5,
        )
        if sha.returncode != 0:
            return ""
        build = sha.stdout.strip()
        if not build:
            return ""
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=root, capture_output=True, text=True, timeout=5,
        )
        if status.returncode == 0 and status.stdout.strip():
            build = f"{build}-dirty"
        return build
    except (OSError, subprocess.SubprocessError):
        return ""


def _build_id() -> str:
    """Build id from the image/env (``BRG_BUILD_SHA``), else from git, else ``nogit``."""
    env = os.environ.get("BRG_BUILD_SHA", "").strip()
    if env:
        return env
    return _git_build_id() or "nogit"


__build__ = _build_id()
__version_label__ = f"{__version__}-{__build__}"


def version_label() -> str:
    """Human-facing version string, e.g. ``1.31.1-g3f161d0-dirty``."""
    return __version_label__

