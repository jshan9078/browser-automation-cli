import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from playwright.async_api import Browser, BrowserContext, Page

logger = logging.getLogger(__name__)


@dataclass
class Session:
    id: str
    context: BrowserContext
    page: Page
    created_at: float = field(default_factory=time.time)

    @property
    def url(self) -> str:
        return self.page.url


class SessionManager:
    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()
        logger.info("SessionManager initialized")

    async def create(self, browser: Browser) -> Session:
        async with self._lock:
            session_id = uuid.uuid4().hex[:8]
            
            # Set explicit desktop user agent
            user_agent = (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            )
            
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=user_agent,
            )
            
            # Hide navigator.webdriver to avoid automation detection
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                    configurable: true
                });
            """)
            
            page = await context.new_page()
            await page.set_viewport_size({"width": 1920, "height": 1080})
            session = Session(id=session_id, context=context, page=page)
            self._sessions[session_id] = session
            logger.info(f"Created session {session_id}")
            return session

    async def get(self, session_id: str) -> Optional[Session]:
        async with self._lock:
            return self._sessions.get(session_id)

    async def list(self) -> list[dict[str, Any]]:
        async with self._lock:
            result = []
            for s in self._sessions.values():
                result.append({
                    "session_id": s.id,
                    "url": s.url,
                    "title": await s.page.title(),
                })
            return result

    async def delete(self, session_id: str) -> bool:
        async with self._lock:
            if session_id in self._sessions:
                session = self._sessions.pop(session_id)
                await session.context.close()
                logger.info(f"Deleted session {session_id}")
                return True
            return False

    async def close_all(self):
        async with self._lock:
            logger.info(f"Closing {len(self._sessions)} sessions")
            for session in self._sessions.values():
                await session.context.close()
            self._sessions.clear()
