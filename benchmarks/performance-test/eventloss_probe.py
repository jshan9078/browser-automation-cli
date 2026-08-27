"""Are timers/fetch callbacks that fire while Emulation.setScriptExecutionDisabled=true lost or deferred?"""
import asyncio, subprocess, sys, time
from playwright.async_api import async_playwright
sys.argv, _a = sys.argv[:1], sys.argv; import run as r; sys.argv = _a
PORT=8767
site = subprocess.Popen([r.PY, str(r.SITE/"server.py"), str(PORT)])
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context(); page = await ctx.new_page(); cdp = await ctx.new_cdp_session(page)
        await page.goto(f"http://127.0.0.1:{PORT}/page2.html")
        await page.evaluate("""() => { window.log = [];
            setTimeout(() => log.push('timeout3s'), 3000);
            setInterval(() => log.push('interval'), 1000);
            fetch('/page2.html?x=' + Math.random()).then(() => new Promise(r => setTimeout(r, 2500))).then(() => log.push('fetch-chain'));
            const ws = new Promise(r => setTimeout(r, 2000)).then(() => log.push('promise2s'));
            requestAnimationFrame(function f(){ log.push('raf'); });
            document.addEventListener('click', () => log.push('click'));
        }""")
        await cdp.send("Emulation.setScriptExecutionDisabled", {"value": True})
        await asyncio.sleep(4.5)
        await cdp.send("Emulation.setScriptExecutionDisabled", {"value": False})
        await asyncio.sleep(1.5)
        await page.mouse.click(10, 10)
        print("log after thaw:", await page.evaluate("() => window.log"))
        await b.close()
asyncio.run(main()); site.terminate()
