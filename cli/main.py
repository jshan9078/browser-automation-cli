#!/usr/bin/env python3
"""browser — thin client for browser-daemon. Stays free of Playwright imports on the daemon path (~40ms per call)."""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

SOCKET_PATH = Path.home() / ".browser-daemon" / "socket"

HELP = """browser — authenticated browser automation for coding agents

Standalone (no daemon):
  browser capture <url> [-f] [-o path]   Headless screenshot (viewport; -f full page)
  browser install                        Install Chromium runtime
  browser cleanup                        Kill Chromium processes started by this tool
  browser --version | update             Show version / upgrade to the latest release (checked daily; BROWSER_NO_UPDATE_CHECK=1 disables)

Daemon (start with: browser-daemon):
  browser create [--show]                New session (headless; --show opens a window, e.g. to log in)
  browser list [--table]                 Sessions as JSON (--table for humans)
  browser <id> show | hide               Move the session to a visible window / back to headless
  browser <id> delete                    Close session and forget its cookies
  browser shutdown                       Stop the daemon (sessions are saved and restored on next start)

Page commands (all print JSON; add -s/--snapshot to include a fresh snapshot in the result):
  browser <id> navigate <url> [--wait load|domcontentloaded|networkidle]
  browser <id> snapshot [scope-selector] [--all] [--max N] [--json]
                                         Interactive elements as "@e12 button "Create"" lines.
                                         --all adds text blocks; --json gives structured output
  browser <id> click <target> [--double]
  browser <id> type <target> <text> [--sequential] [--submit]
  browser <id> press <key> [target]      e.g. Enter, Tab, Control+a
  browser <id> hover <target>
  browser <id> select <target> <value>   <select> by value or label
  browser <id> scroll [up|down] [px]     or: scroll <target> to bring it into view
  browser <id> text [selector]           Readable text of the page or element
  browser <id> wait [--text T | --selector S] [--gone] [--timeout ms]
  browser <id> screenshot [target] [-o path] [-f] [-q quality]
  browser <id> eval <js-expression>
  browser <id> console [--clear]
  browser <id> back | forward
  browser <id> batch                     Read JSON lines {"action":..,"params":{..}} from stdin,
                                         run them in order in one round-trip, stop at first failure

Targets: @e12 (ref from snapshot, preferred) | CSS selector | text=Create | role=button[name=Create]
         | label=Widget name | placeholder=Search — or flags --text/--role/--name/--label/--placeholder.
"""


# ---------------------------------------------------------------------------
async def send_request(request: dict) -> dict:
    try:
        for attempt in range(5):  # daemon may be (re)starting
            try:
                reader, writer = await asyncio.open_unix_connection(str(SOCKET_PATH))
                break
            except (FileNotFoundError, ConnectionRefusedError):
                if attempt == 4:
                    raise
                await asyncio.sleep(0.1)
        writer.write(json.dumps(request).encode())
        await writer.drain()
        writer.write_eof()
        data = await reader.read()
        writer.close()
        await writer.wait_closed()
        return json.loads(data.decode())
    except FileNotFoundError:
        return {"success": False, "error": "Daemon not running. Start with: browser-daemon"}
    except ConnectionRefusedError:
        return {"success": False, "error": "Connection refused. Is another daemon running?"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def out(result: dict):
    """Print results compactly: snapshot text as-is, everything else as JSON."""
    snap = result.pop("snapshot", None) if isinstance(result, dict) else None
    if snap is not None and result.get("success") and set(result) <= {"success", "url", "title", "settled", "warning"}:
        print(snap)
    else:
        print(json.dumps(result, indent=2))
        if snap is not None:
            print(snap)
    if isinstance(result, dict) and not result.get("success", True):
        sys.exit(1)


def parse_flags(args: list[str], bools: set, valued: set) -> tuple[list[str], dict]:
    """Split positional args from --flags. Values for `valued` flags take the next arg."""
    pos, flags, i = [], {}, 0
    while i < len(args):
        a = args[i]
        if a in bools:
            flags[a.lstrip("-")] = True
        elif a in valued and i + 1 < len(args):
            flags[a.lstrip("-")] = args[i + 1]
            i += 1
        elif a.startswith("--") and "=" in a:
            k, v = a[2:].split("=", 1)
            flags[k] = v
        else:
            pos.append(a)
        i += 1
    return pos, flags


TARGET_FLAGS = {"--text", "--role", "--name", "--label", "--placeholder"}
COMMON_BOOLS = {"-s", "--snapshot"}


def target_params(flags: dict) -> dict:
    p = {k: flags[k] for k in ("text", "role", "name", "label", "placeholder") if k in flags}
    if flags.get("s") or flags.get("snapshot"):
        p["snap"] = True
    return p


def build(session_id: str, action: str, rest: list[str]) -> Optional[dict]:
    """Translate CLI words into one daemon request. Returns None for unknown actions."""
    pos, f = parse_flags(rest, COMMON_BOOLS | {"--all", "--json", "--double", "--sequential", "--submit", "--gone",
                                               "-f", "--full-page", "--clear", "--table"},
                         TARGET_FLAGS | {"--wait", "--max", "--timeout", "-o", "--output", "-q", "--quality",
                                         "--selector", "--format"})
    tp = target_params(f)
    req = lambda a, p: {"action": a, "session_id": session_id, "params": p}
    if action == "navigate" and pos:
        p = {"url": pos[0], **tp}
        if "wait" in f: p["wait"] = f["wait"]
        if "timeout" in f: p["timeout"] = float(f["timeout"])
        return req("navigate", p)
    if action == "snapshot":
        p = {}
        if pos: p["selector"] = pos[0]
        if f.get("all"): p["all"] = True
        if "max" in f: p["max"] = int(f["max"])
        if f.get("json") or f.get("format") == "json": p["format"] = "json"
        return req("snapshot", p)
    if action == "click":
        p = {"selector": pos[0] if pos else "", **tp}
        if f.get("double"): p["double"] = True
        return req("click", p)
    if action == "type":
        if tp.keys() - {"snap"}:
            text = pos[0] if pos else ""; sel = ""
        elif len(pos) >= 2:
            sel, text = pos[0], pos[1]
        else:
            return None
        p = {"selector": sel, "text_value": text, **tp}
        if f.get("sequential"): p["sequential"] = True
        if f.get("submit"): p["submit"] = True
        return req("type", p)
    if action == "press" and pos:
        return req("press_key", {"key": pos[0], "selector": pos[1] if len(pos) > 1 else "", **tp})
    if action == "hover":
        return req("hover", {"selector": pos[0] if pos else "", **tp})
    if action == "select":
        if tp.keys() - {"snap"} and pos:
            return req("select_option", {"selector": "", "value": pos[0], **tp})
        if len(pos) >= 2:
            return req("select_option", {"selector": pos[0], "value": pos[1], **tp})
        return None
    if action == "scroll":
        p = {**tp}
        for a in pos:
            if a in ("up", "down"): p["direction"] = a
            elif a.lstrip("-").isdigit(): p["amount"] = int(a)
            else: p["selector"] = a
        return req("scroll", p)
    if action == "text":
        p = {}
        if pos: p["selector"] = pos[0]
        if "max" in f: p["max"] = int(f["max"])
        return req("text", p)
    if action == "wait":
        p = {}
        if "text" in f: p["text"] = f["text"]
        if "selector" in f: p["selector"] = f["selector"]
        elif pos: p["selector"] = pos[0]
        if f.get("gone"): p["gone"] = True
        if "timeout" in f: p["timeout"] = float(f["timeout"])
        return req("wait", p)
    if action == "screenshot":
        p = {k: v for k, v in tp.items() if k != "snap"}
        if pos: p["selector"] = pos[0]
        o = f.get("o") or f.get("output")
        if o: p["output"] = o
        if f.get("f") or f.get("full-page"): p["full_page"] = True
        q = f.get("q") or f.get("quality")
        if q: p["quality"] = int(q)
        return req("screenshot", p)
    if action == "eval" and pos:
        return req("eval", {"expression": " ".join(pos)})
    if action == "console":
        return req("console_logs", {"clear": bool(f.get("clear"))})
    if action == "back":
        return req("go_back", tp)
    if action == "forward":
        return req("go_forward", tp)
    if action in ("show", "hide", "delete"):
        return {"action": action, "session_id": session_id}
    return None


# ---------------------------------------------------------------------------
async def cmd_capture(url: str, full_page: bool = False, output: Optional[str] = None):
    """Standalone screenshot without the daemon."""
    import time
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="load", timeout=30000)
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
            shot = await page.screenshot(full_page=full_page, type="jpeg", quality=70)
            path = Path(output).expanduser() if output else Path("/tmp") / f"browser_capture_{int(time.time())}.jpg"
            path.write_bytes(shot)
            print(json.dumps({"success": True, "path": str(path), "full_page": full_page, "format": "jpeg"}))
        except Exception as e:
            print(json.dumps({"success": False, "error": str(e)}), file=sys.stderr)
            sys.exit(1)
        finally:
            await context.close()
            await browser.close()


def cmd_install():
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        print("Installed Chromium for Browser CLI")
    except subprocess.CalledProcessError as e:
        print(f"Error: failed to install Chromium ({e.returncode})", file=sys.stderr)
        sys.exit(1)


def cmd_cleanup():
    """Kill only Chromium processes launched from Playwright's browser cache (not other tools' browsers)."""
    ps = subprocess.run(["ps", "-Ao", "pid,command"], capture_output=True, text=True).stdout
    killed = 0
    for line in ps.splitlines()[1:]:
        pid, _, cmd = line.strip().partition(" ")
        if "ms-playwright" in cmd and ("chrom" in cmd.lower()):
            try:
                os.kill(int(pid), 15)
                killed += 1
            except Exception:
                pass
    print(f"Killed {killed} Chromium process(es)" if killed else "No Playwright Chromium processes found")


async def cmd_batch(session_id: str):
    reqs = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if "action" in r and "session_id" not in r:
            r["session_id"] = session_id
        elif "cmd" in r:  # {"cmd": "click @e3 -s"} shorthand
            words = r["cmd"].split()
            r = build(session_id, words[0], words[1:]) or {"action": "unknown"}
        reqs.append(r)
    result = await send_request({"action": "batch", "requests": reqs})
    print(json.dumps(result, indent=2))
    if not result.get("success") or any(not r.get("success") for r in result.get("results", [])):
        sys.exit(1)


async def _main(args: list[str]):
    cmd = args[0]
    if cmd == "capture" and len(args) >= 2:
        pos, f = parse_flags(args[1:], {"-f", "--full-page"}, {"-o", "--output"})
        await cmd_capture(pos[0], full_page=bool(f.get("f") or f.get("full-page")), output=f.get("o") or f.get("output"))
    elif cmd == "install":
        cmd_install()
    elif cmd == "cleanup":
        cmd_cleanup()
    elif cmd == "create":
        visible = any(a in ("--show", "--visible", "--headed") for a in args[1:])
        r = await send_request({"action": "create", "params": {"visible": visible}})
        if r.get("success"):
            print(r["session_id"])
        else:
            print(f"Error: {r.get('error')}", file=sys.stderr)
            sys.exit(1)
    elif cmd == "list":
        r = await send_request({"action": "list"})
        if not r.get("success"):
            print(f"Error: {r.get('error')}", file=sys.stderr)
            sys.exit(1)
        if "--table" in args:
            print(f"{'SESSION_ID':<10} {'STATE':<11} {'VIS':<4} {'URL':<50} TITLE")
            for s in r["sessions"]:
                print(f"{s['session_id']:<10} {s['state']:<11} {'yes' if s['visible'] else 'no':<4} {(s['url'] or '')[:48]:<50} {(s['title'] or '')[:30]}")
        else:
            print(json.dumps(r["sessions"], indent=2))
    elif cmd == "shutdown":
        out(await send_request({"action": "shutdown"}))
    elif cmd == "delete" and len(args) >= 2:
        out(await send_request({"action": "delete", "session_id": args[1]}))
    elif len(args) >= 2:
        session_id, action, rest = args[0], args[1], args[2:]
        if action == "batch":
            await cmd_batch(session_id)
            return
        req = build(session_id, action, rest)
        if req is None:
            print(f"Unknown action or missing args: {action}\n", file=sys.stderr)
            print(HELP, file=sys.stderr)
            sys.exit(2)
        out(await send_request(req))
    else:
        print(HELP, file=sys.stderr)
        sys.exit(2)


def _update_notice():
    try:
        from daemon import update
        n = update.notice()
        if n:
            print(n, file=sys.stderr)
    except Exception:
        pass


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(HELP)
        _update_notice()
        return
    if args[0] in ("--version", "-V", "version"):
        from daemon import update
        c = update.read_cache()
        print(json.dumps({"version": update.current_version(), "latest": update.cached_latest(), "checked_at": c.get("checked_at")}))
        _update_notice()
        return
    if args[0] == "update":
        from daemon import update
        info = update.check_now()
        if info.get("error"):
            print(f"Could not reach PyPI: {info['error']}", file=sys.stderr); sys.exit(1)
        if update.is_newer(info["latest"], info["current"]):
            print(f"{info['latest']} available (you have {info['current']}). Upgrading with: uv tool upgrade {update.PACKAGE}")
            r = subprocess.run(["uv", "tool", "upgrade", update.PACKAGE])
            if r.returncode != 0:
                print("Upgrade failed; run it manually: uv tool upgrade browser-automation-cli", file=sys.stderr); sys.exit(r.returncode)
            print("Restart the daemon to use the new version: browser shutdown && browser-daemon &")
        else:
            print(f"Up to date ({info['current']}).")
        return
    try:
        asyncio.run(_main(args))
    finally:
        _update_notice()


if __name__ == "__main__":
    main()
