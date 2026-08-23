"""Can Chromium's own background-tab throttling replace freezing? Playwright disables it by default."""
import asyncio, os, sys, time
from playwright.async_api import async_playwright
sys.argv, _a = sys.argv[:1], sys.argv; import freeze_probe as fp; sys.argv = _a
URL = "https://dash.cloudflare.com/login"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
IGN = ["--disable-background-timer-throttling", "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows", "--disable-ipc-flooding-protection"]
async def main(headless):
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=headless, args=fp.ARGS, ignore_default_args=IGN)
        ctx = await b.new_context(viewport={"width":1280,"height":800}, user_agent=UA); page = await ctx.new_page()
        cdp = await ctx.new_cdp_session(page)
        await page.goto(URL, wait_until="load"); await asyncio.sleep(3)
        print(f"[headless={headless}] active      :", fp.measure(os.getpid()))
        # background the page by bringing another page to front
        p2 = await ctx.new_page(); await p2.goto("about:blank"); await p2.bring_to_front(); await asyncio.sleep(3)
        print(f"[headless={headless}] backgrounded:", fp.measure(os.getpid()))
        await cdp.send("Page.setWebLifecycleState", {"state": "frozen"}); await asyncio.sleep(2)
        print(f"[headless={headless}] +frozen     :", fp.measure(os.getpid()))
        await cdp.send("Page.setWebLifecycleState", {"state": "active"})
        await page.bring_to_front(); await asyncio.sleep(2)
        print(f"[headless={headless}] foreground  :", fp.measure(os.getpid()))
        # visibility override without tab switching
        await p2.close()
        await cdp.send("Emulation.setAutoDarkModeOverride", {}) if False else None
        r = await page.evaluate("document.visibilityState"); print("visibilityState when front:", r)
        await b.close()
asyncio.run(main(True))
