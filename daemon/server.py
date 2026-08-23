import asyncio
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

from playwright.async_api import Browser, async_playwright

from .browser import ACTIONS
from .session import SessionManager
from . import update

logger = logging.getLogger(__name__)

SOCKET_PATH = Path.home() / ".browser-daemon" / "socket"
REQUEST_LOG = Path.home() / ".browser-daemon" / "requests.log"  # one JSON line per request: audit + benchmarking

# Chrome for Testing has no hardware compositing on macOS: a headed window at
# 1920x1080 burns >150% CPU in the GPU helper on animated pages (see AUDIT.md).
LAUNCH_ARGS = [
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-gpu",
    "--force-prefers-reduced-motion",
    "--disable-background-networking",
    "--disable-component-update",
    "--no-first-run",
    "--no-default-browser-check",
]
if sys.platform.startswith("linux"):
    LAUNCH_ARGS.append("--no-sandbox")  # only needed in containers


class Daemon:
    def __init__(self):
        self.playwright = None
        self.headless: Optional[Browser] = None
        self.headed: Optional[Browser] = None
        self.server = None
        self._browser_lock = asyncio.Lock()
        self._shutdown = asyncio.Event()
        self.sessions = SessionManager(self.get_browser, self.close_browsers)

    # ---- browsers are launched lazily: headless for agent work, headed only while a session is `show`n
    async def get_browser(self, visible: bool) -> Browser:
        async with self._browser_lock:
            attr = "headed" if visible else "headless"
            b = getattr(self, attr)
            if b is None or not b.is_connected():
                logger.info(f"Launching {attr} browser")
                b = await self.playwright.chromium.launch(headless=not visible, args=LAUNCH_ARGS)
                setattr(self, attr, b)
            return b

    async def close_browsers(self, keep_headed: bool = False, keep_headless: bool = False):
        async with self._browser_lock:
            for attr, keep in (("headed", keep_headed), ("headless", keep_headless)):
                b = getattr(self, attr)
                if b is not None and not keep:
                    logger.info(f"Closing idle {attr} browser")
                    try:
                        await b.close()
                    except Exception:
                        pass
                    setattr(self, attr, None)

    async def start(self):
        logger.info("Starting browser daemon...")
        os.makedirs(SOCKET_PATH.parent, exist_ok=True)
        os.chmod(SOCKET_PATH.parent, 0o700)
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()

        update.start_background_checks()
        self.playwright = await async_playwright().start()
        # warm the headless browser so the first `create` is fast
        await self.get_browser(False)

        self.server = await asyncio.start_unix_server(self.handle_client, path=str(SOCKET_PATH))
        os.chmod(SOCKET_PATH, 0o600)  # any local user could otherwise drive logged-in sessions
        self._socket_ino = os.stat(SOCKET_PATH).st_ino
        logger.info(f"Daemon ready, socket at {SOCKET_PATH}")
        await self._shutdown.wait()

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            data = await reader.read()  # CLI sends EOF after the request; read until then
            if not data:
                return
            request = json.loads(data.decode())
            logger.debug(f"Received: {request}")
            t0 = time.time()
            if request.get("action") == "batch":
                response = {"success": True, "results": [await self.process(r) for r in request.get("requests", [])]}
            else:
                response = await self.process(request)
            payload = json.dumps(response).encode()
            writer.write(payload)
            await writer.drain()
            self._log_request(request, response, time.time() - t0, len(payload))
        except Exception as e:
            logger.error(f"Client error: {e}")
            try:
                writer.write(json.dumps({"success": False, "error": str(e)}).encode())
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def process(self, request: dict) -> dict:
        action = request.get("action")
        session_id = request.get("session_id")
        params = request.get("params", {}) or {}

        if action == "create":
            session = await self.sessions.create(visible=bool(params.get("visible", False)))
            return {"success": True, "session_id": session.id, "visible": session.visible}
        if action == "list":
            return {"success": True, "sessions": await self.sessions.list()}
        if action == "shutdown":
            asyncio.get_running_loop().create_task(self.stop())
            return {"success": True}

        if not session_id:
            return {"success": False, "error": "session_id required for this action"}

        if action == "delete":
            deleted = await self.sessions.delete(session_id)
            return {"success": deleted, "error": None if deleted else "Session not found"}
        if action in ("show", "hide"):
            ok = await self.sessions.set_visible(session_id, action == "show")
            return {"success": ok, "error": None if ok else "Session not found"}

        if action not in ACTIONS:
            return {"success": False, "error": f"Unknown action: {action}"}

        session = await self.sessions.get(session_id)
        if not session:
            return {"success": False, "error": f"Session {session_id} not found"}
        session.busy += 1
        try:
            result = await ACTIONS[action](session, **params)
            try:
                session.title = await session.page.title()
            except Exception:
                pass
            return result
        except TypeError as e:
            return {"success": False, "error": f"Bad params for {action}: {e}"}
        finally:
            session.busy -= 1
            session.last_used = time.time()

    def _log_request(self, request: dict, response: dict, dur: float, nbytes: int):
        try:
            sub = request.get("requests") if request.get("action") == "batch" else None
            entry = {"t": round(time.time(), 3), "dur": round(dur, 4), "session": request.get("session_id") or (sub[0].get("session_id") if sub else None),
                     "action": request.get("action"), "params": request.get("params"), "batch": [r.get("action") for r in sub] if sub else None,
                     "ok": bool(response.get("success")), "bytes": nbytes}
            with open(REQUEST_LOG, "a") as f:
                f.write(json.dumps(entry) + "\n")
            os.chmod(REQUEST_LOG, 0o600)
        except Exception as e:
            logger.debug(f"request log failed: {e}")

    async def stop(self):
        if self._shutdown.is_set():
            return
        logger.info("Stopping daemon...")
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        await self.sessions.close_all(persist=True)
        await self.close_browsers()
        if self.playwright:
            await self.playwright.stop()
        try:  # only remove the socket if it is still ours (a newer daemon may have replaced it)
            if os.stat(SOCKET_PATH).st_ino == getattr(self, "_socket_ino", None):
                SOCKET_PATH.unlink()
        except FileNotFoundError:
            pass
        self._shutdown.set()
        logger.info("Daemon stopped")


async def _run():
    daemon = Daemon()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(daemon.stop()))
    await daemon.start()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
