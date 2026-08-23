import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from playwright.async_api import Browser, BrowserContext, CDPSession, Page

logger = logging.getLogger(__name__)

# 1280x800 is what Anthropic/OpenAI computer-use tooling targets: desktop layouts,
# 2.3x fewer pixels than 1920x1080 to composite and screenshot.
VIEWPORT = {"width": 1280, "height": 800}

STATE_DIR = Path.home() / ".browser-daemon" / "sessions"
FREEZE_AFTER_S = float(os.environ.get("BROWSER_FREEZE_AFTER", "10"))
HIBERNATE_AFTER_S = float(os.environ.get("BROWSER_HIBERNATE_AFTER", "600"))

BrowserGetter = Callable[[bool], Awaitable[Browser]]
CONSOLE_MAX = 200


@dataclass
class Session:
    id: str
    visible: bool = False
    context: Optional[BrowserContext] = None
    page: Optional[Page] = None
    cdp: Optional[CDPSession] = None
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    frozen: bool = False
    busy: int = 0  # commands in flight; never freeze/hibernate a busy session
    title: str = ""
    # set while hibernated (no live context)
    saved_url: str = "about:blank"
    saved_state: Optional[dict] = None
    refs: dict = field(default_factory=dict)  # snapshot ref -> element handle
    console: list = field(default_factory=list)

    @property
    def live(self) -> bool:
        return self.page is not None

    @property
    def url(self) -> str:
        return self.page.url if self.page else self.saved_url


class SessionManager:
    def __init__(self, get_browser: BrowserGetter, close_browsers: Callable[..., Awaitable[None]]):
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()
        self._get_browser = get_browser
        self._close_browsers = close_browsers
        self._housekeeper: Optional[asyncio.Task] = None
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(STATE_DIR, 0o700)
        self._load_hibernated()
        logger.info("SessionManager initialized")

    # ---- persistence --------------------------------------------------------
    def _load_hibernated(self):
        for f in STATE_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                s = Session(id=f.stem, saved_url=data.get("url", "about:blank"), saved_state=data.get("state"),
                            created_at=data.get("created_at", time.time()), title=data.get("title", ""))
                self._sessions[s.id] = s
            except Exception as e:
                logger.warning(f"Could not load session {f}: {e}")
        if self._sessions:
            logger.info(f"Loaded {len(self._sessions)} hibernated session(s)")

    async def _save(self, s: Session):
        if s.live:
            try:
                s.saved_state = await s.context.storage_state()
                s.saved_url = s.page.url
            except Exception as e:
                logger.warning(f"storage_state failed for {s.id}: {e}")
        f = STATE_DIR / f"{s.id}.json"
        f.write_text(json.dumps({"url": s.saved_url, "state": s.saved_state, "created_at": s.created_at, "title": s.title}))
        os.chmod(f, 0o600)

    # ---- lifecycle ----------------------------------------------------------
    async def _attach(self, s: Session, visible: bool, url: Optional[str] = None):
        """Create (or re-create) the live context for a session in the headed or headless browser."""
        browser = await self._get_browser(visible)
        context = await browser.new_context(viewport=VIEWPORT, user_agent=_user_agent(browser), storage_state=s.saved_state)
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined, configurable: true});"
        )
        page = await context.new_page()
        page.on("console", lambda m: _buffer_console(s, m))
        s.context, s.page, s.visible, s.frozen = context, page, visible, False
        s.cdp = await context.new_cdp_session(page)
        s.refs = {}
        target = url or s.saved_url
        if target and target != "about:blank":
            try:
                await page.goto(target, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                logger.warning(f"re-navigation to {target} failed: {e}")

    async def _detach(self, s: Session):
        if not s.live:
            return
        if s.frozen:  # a paused renderer cannot answer storage_state(); thaw first
            await self._set_lifecycle(s, "active")
        await self._save(s)
        try:
            await s.context.close()
        except Exception:
            pass
        s.context = s.page = s.cdp = None
        s.refs = {}
        s.frozen = False

    async def create(self, visible: bool = False) -> Session:
        async with self._lock:
            s = Session(id=uuid.uuid4().hex[:8])
            await self._attach(s, visible)
            self._sessions[s.id] = s
            await self._save(s)
            self._ensure_housekeeper()
            logger.info(f"Created session {s.id} (visible={visible})")
            return s

    async def get(self, session_id: str, wake: bool = True) -> Optional[Session]:
        """Return a session ready for commands: rehydrated if hibernated, thawed if frozen."""
        async with self._lock:
            s = self._sessions.get(session_id)
            if not s:
                return None
            if wake:
                if not s.live:
                    await self._attach(s, s.visible)
                elif s.frozen:
                    await self._set_lifecycle(s, "active")
                s.last_used = time.time()
                self._ensure_housekeeper()
            return s

    async def set_visible(self, session_id: str, visible: bool) -> bool:
        """Move a session between the headless and headed browsers, keeping cookies/storage and URL."""
        async with self._lock:
            s = self._sessions.get(session_id)
            if not s:
                return False
            if s.live and s.visible == visible:
                return True
            url = s.url
            await self._detach(s)
            await self._attach(s, visible, url)
            s.last_used = time.time()
            self._ensure_housekeeper()
            await self._maybe_close_idle_browsers()
            return True

    async def list(self) -> list[dict[str, Any]]:
        async with self._lock:
            return [{
                "session_id": s.id,
                "url": s.url,
                "title": s.title,
                "state": "hibernated" if not s.live else "frozen" if s.frozen else "active",
                "visible": s.visible,
            } for s in self._sessions.values()]

    async def delete(self, session_id: str) -> bool:
        async with self._lock:
            s = self._sessions.pop(session_id, None)
            if not s:
                return False
            if s.live:
                try:
                    await s.context.close()
                except Exception:
                    pass
            (STATE_DIR / f"{s.id}.json").unlink(missing_ok=True)
            logger.info(f"Deleted session {session_id}")
            await self._maybe_close_idle_browsers()
            return True

    async def close_all(self, persist: bool = True):
        async with self._lock:
            if self._housekeeper:
                self._housekeeper.cancel()
            logger.info(f"Closing {len(self._sessions)} sessions (persist={persist})")
            for s in list(self._sessions.values()):
                if persist:
                    await self._detach(s)
                elif s.live:
                    await s.context.close()
            if not persist:
                self._sessions.clear()

    # ---- idle handling ------------------------------------------------------
    async def _set_lifecycle(self, s: Session, state: str):
        """Freeze/thaw a hidden page by disabling script execution.

        Measured on the Cloudflare dashboard (headless): 89% -> 3% CPU. Alternatives tried and
        rejected: Page.setWebLifecycleState / background-tab throttling (no effect: Playwright
        disables throttling and headless pages are never hidden), Debugger.pause (only takes
        effect at the next JS statement, so quiet pages never pause and resume fails), virtual
        time (freezes Date.now and replays missed timers in a burst). Trade-off: timer/fetch
        callbacks that fire *while* frozen are dropped, which is why freezing waits
        FREEZE_AFTER_S of idle and only applies to hidden sessions. BROWSER_FREEZE_AFTER=0 disables.
        """
        if not s.cdp:
            return
        try:
            await s.cdp.send("Emulation.setScriptExecutionDisabled", {"value": state == "frozen"})
            s.frozen = state == "frozen"
        except Exception as e:
            logger.debug(f"setScriptExecutionDisabled({state}) failed for {s.id}: {e}")

    def _ensure_housekeeper(self):
        if self._housekeeper is None or self._housekeeper.done():
            self._housekeeper = asyncio.create_task(self._housekeep())

    async def _housekeep(self):
        try:
            while True:
                await asyncio.sleep(1)
                now = time.time()
                async with self._lock:
                    any_live = False
                    for s in self._sessions.values():
                        if not s.live or s.busy:
                            continue
                        any_live = True
                        idle = now - s.last_used
                        if HIBERNATE_AFTER_S and idle > HIBERNATE_AFTER_S:
                            logger.info(f"Hibernating idle session {s.id}")
                            await self._detach(s)
                        elif FREEZE_AFTER_S and not s.visible and not s.frozen and idle > FREEZE_AFTER_S:
                            await self._set_lifecycle(s, "frozen")
                    await self._maybe_close_idle_browsers()
                    if not any_live and not any(x.busy for x in self._sessions.values()):
                        return
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"housekeeper error: {e}")

    async def _maybe_close_idle_browsers(self):
        live_visible = any(s.live and s.visible for s in self._sessions.values())
        live_hidden = any(s.live and not s.visible for s in self._sessions.values())
        await self._close_browsers(keep_headed=live_visible, keep_headless=live_hidden)


def _user_agent(browser: Browser) -> str:
    """Desktop UA derived from the real runtime version (a pinned, mismatched UA is a bot signal)."""
    major = browser.version.split(".")[0]
    return (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
    )


def _buffer_console(s: Session, msg):
    s.console.append({"type": msg.type, "text": msg.text, "t": time.time()})
    del s.console[:-CONSOLE_MAX]
