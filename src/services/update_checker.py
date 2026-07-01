"""
Checks GitHub for a newer version of WorkTimer once per day.
"""

import asyncio
import logging
import urllib.request
import tomllib
from datetime import datetime, timedelta
from pathlib import Path

from nicegui import app

logger = logging.getLogger(__name__)

# Local pyproject.toml lives two directories above this file (src/services/ → root)
_LOCAL_PYPROJECT = Path(__file__).parent.parent.parent / "pyproject.toml"
_PYPROJECT_URL = (
    "https://raw.githubusercontent.com/mackant/worktimer"
    "/refs/heads/main/pyproject.toml"
)
_CHECK_INTERVAL = timedelta(hours=24)

# Process-level cache so multiple clients don't re-trigger the network call
_process_cache: dict | None = None


def _current_version() -> str:
    """Read version from the local pyproject.toml (always available from source)."""
    try:
        with open(_LOCAL_PYPROJECT, "rb") as f:
            return tomllib.load(f)["project"]["version"]
    except Exception:
        return "unknown"


def _fetch_latest_blocking() -> str:
    """Blocking HTTP fetch — must run in a thread executor."""
    with urllib.request.urlopen(_PYPROJECT_URL, timeout=5) as resp:
        raw = resp.read().decode("utf-8")
    return tomllib.loads(raw)["project"]["version"]


async def check_for_update(force: bool = False) -> dict:
    """
    Return {"available": bool, "latest": str, "current": str}.

    Network call only fires when >24 h have passed since the last check
    (or when force=True). Result is cached process-wide and persisted
    to app.storage.general so other clients see it instantly.
    """
    global _process_cache
    current = _current_version()

    if not force and _process_cache is not None:
        return _process_cache

    # Consult persistent daily gate before hitting the network
    if not force:
        try:
            last_str = app.storage.general.get("update_last_check")
            if last_str:
                elapsed = datetime.now() - datetime.fromisoformat(last_str)
                if elapsed < _CHECK_INTERVAL:
                    latest = app.storage.general.get("update_latest_version", current)
                    # Recompute available against the actual current version (guards
                    # against stale cache from a previous bad version read)
                    available = latest != current
                    _process_cache = {
                        "available": available,
                        "latest": latest,
                        "current": current,
                    }
                    return _process_cache
        except Exception:
            pass

    # Hit the network in a thread so we don't block the event loop
    try:
        loop = asyncio.get_event_loop()
        latest = await loop.run_in_executor(None, _fetch_latest_blocking)
        available = latest != current

        app.storage.general["update_last_check"] = datetime.now().isoformat()
        app.storage.general["update_latest_version"] = latest
        app.storage.general["update_available"] = available

        _process_cache = {"available": available, "latest": latest, "current": current}
        logger.info(f"Update check: current={current}, latest={latest}, available={available}")

    except Exception as exc:
        logger.debug(f"Update check failed: {exc}")
        _process_cache = {"available": False, "latest": current, "current": current}

    return _process_cache
