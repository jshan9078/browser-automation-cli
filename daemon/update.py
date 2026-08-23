"""Once-a-day check of PyPI for a newer release. The daemon does the (network) check and writes
~/.browser-daemon/update.json; the CLI only reads that file, so commands stay fast and offline-safe.
Opt out with BROWSER_NO_UPDATE_CHECK=1."""
import json
import logging
import os
import threading
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)
PACKAGE = "browser-automation-cli"
CACHE = Path.home() / ".browser-daemon" / "update.json"
INTERVAL = 24 * 3600


def current_version() -> str:
    try:
        from importlib.metadata import version
        return version(PACKAGE)
    except Exception:
        return "0.0.0"


def _key(v: str):
    return tuple(int(p) if p.isdigit() else 0 for p in v.split("."))


def is_newer(latest: str, current: str) -> bool:
    return _key(latest) > _key(current)


def fetch_latest(timeout: float = 5.0) -> str:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{PACKAGE}/json", timeout=timeout) as r:
        return json.load(r)["info"]["version"]


def check_now() -> dict:
    info = {"checked_at": time.time(), "current": current_version()}
    try:
        info["latest"] = fetch_latest()
    except Exception as e:
        info["error"] = str(e)
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(info))
    except Exception:
        pass
    return info


def read_cache() -> dict:
    try:
        return json.loads(CACHE.read_text())
    except Exception:
        return {}


def notice() -> str:
    """One-line hint for the CLI to print on stderr, or '' if up to date / unknown / opted out."""
    if os.environ.get("BROWSER_NO_UPDATE_CHECK"):
        return ""
    c = read_cache()
    latest, cur = c.get("latest"), current_version()
    if latest and is_newer(latest, cur):
        return f"browser-automation-cli {latest} is available (you have {cur}): uv tool upgrade {PACKAGE}  (set BROWSER_NO_UPDATE_CHECK=1 to silence)"
    return ""


def start_background_checks():
    """Daemon side: check at start (if the cache is older than a day) and then daily."""
    if os.environ.get("BROWSER_NO_UPDATE_CHECK"):
        return

    def loop():
        while True:
            c = read_cache()
            if time.time() - c.get("checked_at", 0) > INTERVAL:
                info = check_now()
                if info.get("latest") and is_newer(info["latest"], info["current"]):
                    logger.info(f"Update available: {PACKAGE} {info['latest']} (running {info['current']})")
            time.sleep(3600)

    threading.Thread(target=loop, daemon=True, name="update-check").start()
