import base64
import logging
from typing import Any, Optional

from playwright.async_api import Page

logger = logging.getLogger(__name__)


async def navigate(page: Page, url: str) -> dict[str, Any]:
    logger.debug(f"Navigating to {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=10000)
        return {
            "success": True,
            "url": page.url,
            "title": await page.title(),
        }
    except Exception as e:
        logger.error(f"Navigation failed: {e}")
        return {"success": False, "error": str(e)}


async def snapshot(page: Page, selector: Optional[str] = None) -> dict[str, Any]:
    logger.debug(f"Taking snapshot (selector={selector})")
    try:
        # Use page.evaluate to get element data and page state
        result = await page.evaluate("""(selector) => {
            function getSelector(el) {
                // Try to build a good CSS selector
                if (el.id) return '#' + el.id;
                if (el.name && ['input', 'select', 'textarea', 'button'].includes(el.tagName.toLowerCase())) {
                    return el.tagName.toLowerCase() + '[name="' + el.name + '"]';
                }
                if (el.getAttribute('data-testid')) return '[data-testid="' + el.getAttribute('data-testid') + '"]';
                
                // Build class selector
                const classes = Array.from(el.classList).filter(c => !c.match(/^[0-9]/)).slice(0, 2);
                if (classes.length > 0) {
                    return el.tagName.toLowerCase() + '.' + classes.join('.');
                }
                
                // Text-based selector for clickable elements
                const text = el.innerText?.trim();
                if (text && text.length < 50 && ['a', 'button'].includes(el.tagName.toLowerCase())) {
                    return el.tagName.toLowerCase() + ':has-text("' + text.replace(/"/g, '\\"') + '")';
                }
                
                // nth-child fallback
                const parent = el.parentElement;
                if (parent) {
                    const siblings = Array.from(parent.children).filter(c => c.tagName === el.tagName);
                    if (siblings.length > 1) {
                        const index = siblings.indexOf(el) + 1;
                        return getSelector(parent) + ' > ' + el.tagName.toLowerCase() + ':nth-child(' + index + ')';
                    }
                    return getSelector(parent) + ' > ' + el.tagName.toLowerCase();
                }
                return el.tagName.toLowerCase();
            }
            
            const elements = selector 
                ? Array.from(document.querySelectorAll(selector))
                : Array.from(document.body.querySelectorAll('*'));
            
            const elementData = elements.slice(0, 100).map((el, i) => {
                const tag = el.tagName.toLowerCase();
                if (['script', 'style', 'meta', 'link', 'noscript'].includes(tag)) return null;
                
                const text = (el.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 150);
                const isInteractive = ['a', 'button', 'input', 'select', 'textarea'].includes(tag) || 
                                      el.onclick || el.getAttribute('role') === 'button';
                
                return {
                    ref: 'el_' + i,
                    tag: tag,
                    selector: getSelector(el),
                    text: text || null,
                    interactive: isInteractive,
                    href: el.href || null,
                    name: el.name || null,
                    placeholder: el.placeholder || null,
                    ariaLabel: el.getAttribute('aria-label') || null,
                };
            }).filter(Boolean);
            
            return {
                elements: elementData,
                scrollY: window.scrollY,
                viewportHeight: window.innerHeight,
                documentHeight: document.documentElement.scrollHeight
            };
        }""", selector)

        return {
            "success": True, 
            "url": page.url,
            "title": await page.title(),
            "scrollY": result["scrollY"],
            "viewportHeight": result["viewportHeight"],
            "documentHeight": result["documentHeight"],
            "elements": result["elements"]
        }
    except Exception as e:
        logger.error(f"Snapshot failed: {e}")
        return {"success": False, "error": str(e)}


async def click(page: Page, selector: str) -> dict[str, Any]:
    logger.debug(f"Clicking {selector}")
    try:
        await page.click(selector, timeout=10000)
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
        return {"success": True, "url": page.url, "title": await page.title()}
    except Exception as e:
        logger.error(f"Click failed: {e}")
        return {"success": False, "error": str(e)}


async def type_text(page: Page, selector: str, text: str) -> dict[str, Any]:
    logger.debug(f"Typing into {selector}")
    try:
        await page.fill(selector, text, timeout=10000)
        return {"success": True}
    except Exception as e:
        logger.error(f"Type failed: {e}")
        return {"success": False, "error": str(e)}


async def hover(page: Page, selector: str) -> dict[str, Any]:
    logger.debug(f"Hovering {selector}")
    try:
        await page.hover(selector, timeout=10000)
        return {"success": True}
    except Exception as e:
        logger.error(f"Hover failed: {e}")
        return {"success": False, "error": str(e)}


async def select_option(page: Page, selector: str, value: str) -> dict[str, Any]:
    logger.debug(f"Selecting {value} in {selector}")
    try:
        await page.select_option(selector, value, timeout=10000)
        return {"success": True}
    except Exception as e:
        logger.error(f"Select failed: {e}")
        return {"success": False, "error": str(e)}


async def press_key(page: Page, key: str) -> dict[str, Any]:
    logger.debug(f"Pressing key {key}")
    try:
        await page.keyboard.press(key)
        return {"success": True}
    except Exception as e:
        logger.error(f"Press failed: {e}")
        return {"success": False, "error": str(e)}


async def screenshot(page: Page, selector: Optional[str] = None, output: Optional[str] = None) -> dict[str, Any]:
    logger.debug(f"Taking screenshot (selector={selector})")
    try:
        from pathlib import Path
        import time
        
        if selector:
            element = await page.query_selector(selector)
            if element:
                image_bytes = await element.screenshot(type="jpeg", quality=85)
            else:
                return {"success": False, "error": f"Element not found: {selector}"}
        else:
            image_bytes = await page.screenshot(type="jpeg", quality=85)

        # Save to file
        if output:
            output_path = Path(output)
        else:
            timestamp = int(time.time())
            filename = f"browser_screenshot_{timestamp}.jpg"
            output_path = Path("/tmp") / filename
        
        output_path.write_bytes(image_bytes)
        
        return {"success": True, "path": str(output_path), "format": "jpeg"}
    except Exception as e:
        logger.error(f"Screenshot failed: {e}")
        return {"success": False, "error": str(e)}


async def console_logs(page: Page) -> dict[str, Any]:
    logger.debug("Getting console logs")
    try:
        logs = await page.evaluate("""() => {
            return window.__browser_logs || [];
        }""")
        return {"success": True, "logs": logs}
    except Exception as e:
        logger.error(f"Console logs failed: {e}")
        return {"success": False, "error": str(e)}


async def go_back(page: Page) -> dict[str, Any]:
    logger.debug("Going back")
    try:
        await page.go_back(wait_until="domcontentloaded", timeout=15000)
        return {"success": True, "url": page.url, "title": await page.title()}
    except Exception as e:
        logger.error(f"Go back failed: {e}")
        return {"success": False, "error": str(e)}


async def go_forward(page: Page) -> dict[str, Any]:
    logger.debug("Going forward")
    try:
        await page.go_forward(wait_until="domcontentloaded", timeout=15000)
        return {"success": True, "url": page.url, "title": await page.title()}
    except Exception as e:
        logger.error(f"Go forward failed: {e}")
        return {"success": False, "error": str(e)}


ACTIONS = {
    "navigate": navigate,
    "snapshot": snapshot,
    "click": click,
    "type": type_text,
    "hover": hover,
    "select_option": select_option,
    "press_key": press_key,
    "screenshot": screenshot,
    "console_logs": console_logs,
    "go_back": go_back,
    "go_forward": go_forward,
}
