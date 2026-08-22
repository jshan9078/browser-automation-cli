import asyncio, subprocess, sys, time
from playwright.async_api import async_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://dash.cloudflare.com/login"

def cpu_of_chrome():
    out = subprocess.run(["ps", "-Aro", "pcpu,comm"], capture_output=True, text=True).stdout
    tot = 0.0; gpu = 0.0
    for line in out.splitlines()[1:]:
        parts = line.strip().split(None, 1)
        if len(parts) < 2: continue
        pc, comm = parts
        if "Chrome for Testing" in comm:
            tot += float(pc)
            if "(GPU)" in comm: gpu += float(pc)
    return tot, gpu

async def run(name, headless, args, viewport):
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=headless, args=args)
        ctx = await b.new_context(viewport=viewport)
        page = await ctx.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        samples = []
        for _ in range(6):
            await asyncio.sleep(2.5)
            samples.append(cpu_of_chrome())
        await b.close()
    tot = sorted(s[0] for s in samples)[len(samples)//2]; gpu = sorted(s[1] for s in samples)[len(samples)//2]
    print(f"{name:55s} total={tot:6.1f}%  gpu-helper={gpu:6.1f}%")

async def main():
    base = ["--disable-dev-shm-usage", "--no-sandbox", "--disable-blink-features=AutomationControlled"]
    await run("A. current: headed, 1920x1080, default GPU", False, base, {"width":1920,"height":1080})
    await run("B. headed, 1280x800, --disable-gpu", False, base+["--disable-gpu"], {"width":1280,"height":800})
    await run("C. headed, 1280x800, --disable-gpu + no animations/bg", False, base+["--disable-gpu","--disable-renderer-backgrounding","--force-prefers-reduced-motion"], {"width":1280,"height":800})
    await run("D. headless (new), 1280x800", True, base, {"width":1280,"height":800})

asyncio.run(main())
