import asyncio, subprocess, sys, time, os
from playwright.async_api import async_playwright
sys.path.insert(0, os.path.dirname(__file__))
sys.argv, _a = sys.argv[:1], sys.argv; import run as _r; sys.argv = _a; descendants, cputimes = _r.descendants, _r.cputimes
URL = sys.argv[1] if len(sys.argv) > 1 else "https://dash.cloudflare.com/login"
ARGS=["--disable-dev-shm-usage","--disable-blink-features=AutomationControlled","--disable-gpu","--force-prefers-reduced-motion","--disable-background-networking"]
def measure(root, interval=4):
    pids=descendants(root); a=cputimes(pids); time.sleep(interval); b=cputimes(pids)
    per={}
    for pid in b:
        if pid in a: per[b[pid][2][:60]]=per.get(b[pid][2][:60],0)+(b[pid][0]-a[pid][0])/interval*100
    return {k:round(v,1) for k,v in sorted(per.items(), key=lambda x:-x[1]) if v>0.5}
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=ARGS)
        ctx = await b.new_context(viewport={"width":1280,"height":800}, user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"); page = await ctx.new_page()
        cdp = await ctx.new_cdp_session(page)
        await page.goto(URL, wait_until="load"); await asyncio.sleep(3)
        print("active     :", measure(os.getpid()))
        await cdp.send("Emulation.setScriptExecutionDisabled", {"value": True}); await asyncio.sleep(2)
        print("noScript 2s:", measure(os.getpid()))
        print("noScript 6s:", measure(os.getpid()))
        await cdp.send("Emulation.setScriptExecutionDisabled", {"value": False}); await asyncio.sleep(1)
        print("resumed    :", measure(os.getpid()))
        print("resumed+5s :", measure(os.getpid()))
        await b.close()
asyncio.run(main())
