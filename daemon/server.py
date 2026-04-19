import asyncio
import json
import logging
import os
import signal
from pathlib import Path

from playwright.async_api import async_playwright

from .browser import ACTIONS
from .session import SessionManager

logger = logging.getLogger(__name__)

SOCKET_PATH = Path.home() / ".browser-daemon" / "socket"


class Daemon:
    def __init__(self):
        self.sessions = SessionManager()
        self.browser = None
        self.browser_launcher = None
        self.server = None
        self._shutdown = asyncio.Event()

    async def start(self):
        logger.info("Starting browser daemon...")

        os.makedirs(SOCKET_PATH.parent, exist_ok=True)

        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()

        self.browser_launcher = await async_playwright().start()
        self.browser = await self.browser_launcher.chromium.launch(
            headless=False,
            args=[
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        logger.info(f"Browser launched, socket at {SOCKET_PATH}")

        self.server = await asyncio.start_unix_server(
            self.handle_client,
            path=str(SOCKET_PATH),
        )

        logger.info("Daemon ready")

        await self._shutdown.wait()

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            data = await reader.read(10 * 1024 * 1024)  # 10MB max
            if not data:
                return

            request = json.loads(data.decode())
            logger.debug(f"Received: {request}")

            response = await self.process(request)
            writer.write(json.dumps(response).encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        except Exception as e:
            logger.error(f"Client error: {e}")
            try:
                writer.write(json.dumps({"success": False, "error": str(e)}).encode())
                await writer.drain()
                writer.close()
            except Exception:
                pass

    async def process(self, request: dict) -> dict:
        action = request.get("action")
        session_id = request.get("session_id")

        if action == "create":
            session = await self.sessions.create(self.browser)
            return {"success": True, "session_id": session.id}

        if action == "list":
            sessions = await self.sessions.list()
            return {"success": True, "sessions": sessions}

        if action == "delete":
            if not session_id:
                return {"success": False, "error": "session_id required"}
            deleted = await self.sessions.delete(session_id)
            return {"success": deleted, "error": None if deleted else "Session not found"}

        if not session_id:
            return {"success": False, "error": "session_id required for this action"}

        session = await self.sessions.get(session_id)
        if not session:
            return {"success": False, "error": f"Session {session_id} not found"}

        if action not in ACTIONS:
            return {"success": False, "error": f"Unknown action: {action}"}

        handler = ACTIONS[action]
        params = request.get("params", {})

        return await handler(session.page, **params)

    async def stop(self):
        logger.info("Stopping daemon...")

        if self.server:
            self.server.close()
            await self.server.wait_closed()

        await self.sessions.close_all()

        if self.browser:
            await self.browser.close()

        if self.browser_launcher:
            await self.browser_launcher.stop()

        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()

        self._shutdown.set()
        logger.info("Daemon stopped")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    daemon = Daemon()
    loop = asyncio.new_event_loop()

    def signal_handler(sig, frame):
        loop.create_task(daemon.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    loop.run_until_complete(daemon.start())


if __name__ == "__main__":
    main()
