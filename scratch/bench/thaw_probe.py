import asyncio, subprocess, sys, time, os
from playwright.async_api import async_playwright
sys.argv, _a = sys.argv[:1], sys.argv; import run as r; sys.argv = _a
PORT=8766
site = subprocess.Popen([r.PY, str(r.SITE/"server.py"), str(PORT)])
ARGS=["--disable-gpu","--force-prefers-reduced-motion","--disable-background-networking"]
async def trial(name, freeze, thaw):
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=ARGS)
        ctx = await b.new_context(viewport={"width":1280,"height":800}); page = await ctx.new_page()
        cdp = await ctx.new_cdp_session(page)
        await page.goto(f"http://127.0.0.1:{PORT}/dashboard.html", wait_until="load")
        await freeze(cdp); await asyncio.sleep(1.5); await thaw(cdp)
        t=time.perf_counter()
        try:
            await page.get_by_text("Create", exact=True).click(timeout=4000)
            st = await page.locator("#status").inner_text(timeout=2000)
            print(f"{name:28s} OK  {time.perf_counter()-t:.2f}s status={st!r}")
        except Exception as e:
            print(f"{name:28s} FAIL {time.perf_counter()-t:.2f}s {str(e).splitlines()[0][:80]}")
        await b.close()
async def main():
    await trial("none", lambda c: asyncio.sleep(0), lambda c: asyncio.sleep(0))
    async def f2(c): await c.send("Emulation.setScriptExecutionDisabled", {"value": True})
    async def t2(c): await c.send("Emulation.setScriptExecutionDisabled", {"value": False})
    await trial("scriptExecutionDisabled", f2, t2)
    async def f3(c): await c.send("Emulation.setVirtualTimePolicy", {"policy": "pause"})
    async def t3(c): await c.send("Emulation.setVirtualTimePolicy", {"policy": "advance"})
    await trial("virtualTime pause", f3, t3)
asyncio.run(main()); site.terminate()
