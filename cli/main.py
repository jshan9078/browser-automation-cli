#!/usr/bin/env python3
import asyncio
import base64
import json
import logging
import subprocess
import sys
from pathlib import Path

SOCKET_PATH = Path.home() / ".browser-daemon" / "socket"


async def cmd_capture(url: str, full_page: bool = True, output: str | None = None):
    """Standalone screenshot capture without daemon. Saves to /tmp."""
    from playwright.async_api import async_playwright
    import time
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        # Create context with anti-detection measures
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        )
        
        # Hide navigator.webdriver to avoid automation detection
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
                configurable: true
            });
        """)
        
        page = await context.new_page()
        
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            # Wait for body to be fully loaded/rendered
            await page.wait_for_selector("body", state="attached")
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(2)  # Additional wait for JS frameworks
            
            # Take screenshot - JPEG for smaller file size
            screenshot_bytes = await page.screenshot(
                full_page=full_page,
                type="jpeg",
                quality=85
            )
            
            # Determine output path
            timestamp = int(time.time())
            if output:
                output_path = Path(output)
            else:
                filename = f"browser_capture_{timestamp}.jpg"
                output_path = Path("/tmp") / filename
            
            output_path.write_bytes(screenshot_bytes)
            
            print(json.dumps({
                "success": True, 
                "path": str(output_path),
                "full_page": full_page,
                "format": "jpeg"
            }))
                
        except Exception as e:
            print(json.dumps({"success": False, "error": str(e)}), file=sys.stderr)
            sys.exit(1)
        finally:
            await context.close()
            await browser.close()


async def send_request(request: dict) -> dict:
    try:
        reader, writer = await asyncio.open_unix_connection(str(SOCKET_PATH))
        writer.write(json.dumps(request).encode())
        await writer.drain()
        writer.write_eof()  # Signal we're done writing
        
        # Read all data until connection is closed
        chunks = []
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            chunks.append(chunk)
        
        data = b''.join(chunks)
        writer.close()
        await writer.wait_closed()
        return json.loads(data.decode())
    except FileNotFoundError:
        return {"success": False, "error": "Daemon not running. Start with: browser-daemon"}
    except ConnectionRefusedError:
        return {"success": False, "error": "Connection refused. Is another daemon running?"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def cmd_create():
    result = await send_request({"action": "create"})
    if result["success"]:
        print(result["session_id"])
    else:
        print(f"Error: {result.get('error')}", file=sys.stderr)
        sys.exit(1)


async def cmd_list():
    result = await send_request({"action": "list"})
    if not result["success"]:
        print(f"Error: {result.get('error')}", file=sys.stderr)
        sys.exit(1)

    sessions = result.get("sessions", [])
    if not sessions:
        print("No active sessions")
        return

    print(f"{'SESSION_ID':<12} {'URL':<50} {'TITLE'}")
    print("-" * 100)
    for s in sessions:
        url = s["url"][:48] if s["url"] else "(empty)"
        title = s["title"][:30] if s["title"] else ""
        print(f"{s['session_id']:<12} {url:<50} {title}")


async def cmd_delete(session_id: str):
    result = await send_request({"action": "delete", "session_id": session_id})
    if result["success"]:
        print(f"Deleted session {session_id}")
    else:
        print(f"Error: {result.get('error')}", file=sys.stderr)
        sys.exit(1)


async def cmd_navigate(session_id: str, url: str):
    result = await send_request({"action": "navigate", "session_id": session_id, "params": {"url": url}})
    print_json(result)


async def cmd_snapshot(session_id: str, selector: str | None):
    params = {"selector": selector} if selector else {}
    result = await send_request({"action": "snapshot", "session_id": session_id, "params": params})
    print_json(result)


async def cmd_click(session_id: str, selector: str):
    result = await send_request({"action": "click", "session_id": session_id, "params": {"selector": selector}})
    print_json(result)


async def cmd_type(session_id: str, selector: str, text: str):
    result = await send_request({"action": "type", "session_id": session_id, "params": {"selector": selector, "text": text}})
    print_json(result)


async def cmd_hover(session_id: str, selector: str):
    result = await send_request({"action": "hover", "session_id": session_id, "params": {"selector": selector}})
    print_json(result)


async def cmd_select_option(session_id: str, selector: str, value: str):
    result = await send_request({"action": "select_option", "session_id": session_id, "params": {"selector": selector, "value": value}})
    print_json(result)


async def cmd_press_key(session_id: str, key: str):
    result = await send_request({"action": "press_key", "session_id": session_id, "params": {"key": key}})
    print_json(result)


async def cmd_screenshot(session_id: str, selector: str | None, output: str | None = None):
    params = {}
    if selector:
        params["selector"] = selector
    if output:
        params["output"] = output
    result = await send_request({"action": "screenshot", "session_id": session_id, "params": params})
    print_json(result)


async def cmd_go_back(session_id: str):
    result = await send_request({"action": "go_back", "session_id": session_id})
    print_json(result)


async def cmd_go_forward(session_id: str):
    result = await send_request({"action": "go_forward", "session_id": session_id})
    print_json(result)


def cmd_install():
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        print("Installed Chromium for Browser CLI")
    except subprocess.CalledProcessError as e:
        print(f"Error: failed to install Chromium ({e.returncode})", file=sys.stderr)
        sys.exit(1)


def cmd_cleanup():
    """Kill all Playwright Chrome processes."""
    try:
        result = subprocess.run(
            ["pkill", "-f", "playwright"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print("Killed Playwright Chrome processes")
        elif result.returncode == 1:
            print("No Playwright processes found")
        else:
            print(f"Error: pkill returned {result.returncode}", file=sys.stderr)
            sys.exit(1)
    except FileNotFoundError:
        print("Error: pkill not found", file=sys.stderr)
        sys.exit(1)


def print_json(data: dict):
    print(json.dumps(data, indent=2))


def main():
    logging.basicConfig(level=logging.WARNING)

    args = sys.argv[1:]

    if len(args) == 0 or args[0] in ("-h", "--help"):
        print("""Browser CLI - Authenticated browser automation

Standalone Commands (no daemon required):
  browser capture <url> [options]       Capture screenshot to /tmp
    Options:
      -f, --full-page                   Capture full page (default: viewport only)
      -o, --output <path>               Custom output path

    Examples:
      browser capture https://example.com
      browser capture https://example.com -f
      browser capture https://example.com -o ./screenshot.jpg

Daemon Commands (requires browser-daemon running):
  browser install                       Install Chromium runtime
  browser cleanup                       Kill stale Chrome processes
  browser create                        Create new session (opens browser for login)
  browser list                          List active sessions
  browser <id> navigate <url>          Navigate to URL
  browser <id> snapshot [selector]      Get page elements
  browser <id> click <selector>         Click element
  browser <id> type <selector> <text>   Type text
  browser <id> hover <selector>         Hover element
  browser <id> select <selector> <val>  Select dropdown option
  browser <id> press <key>              Press keyboard key
  browser <id> screenshot [selector] [-o <path>]
                                        Take screenshot (JPEG, saved to /tmp)
                                        Use -o for custom output path
  browser <id> back                      Go back
  browser <id> forward                   Go forward
  browser <id> delete                    Delete session
  browser -h, --help                    Show this help

Start daemon: browser-daemon
""")
        return

    asyncio.run(_main(args))


async def _main(args: list[str]):
    cmd = args[0]

    if cmd == "capture" and len(args) >= 2:
        url = args[1]
        full_page = True  # Default to full page for better results
        output = None
        
        # Parse flags
        i = 2
        while i < len(args):
            if args[i] in ("-f", "--full-page"):
                full_page = True
                i += 1
            elif args[i] in ("-o", "--output") and i + 1 < len(args):
                output = args[i + 1]
                i += 2
            else:
                i += 1
        
        await cmd_capture(url, full_page=full_page, output=output)
    elif cmd == "install":
        cmd_install()
    elif cmd == "cleanup":
        cmd_cleanup()
    elif cmd == "create":
        await cmd_create()
    elif cmd == "list":
        await cmd_list()
    elif cmd == "delete" and len(args) >= 2:
        await cmd_delete(args[1])
    elif len(args) >= 2:
        session_id = args[0]
        action = args[1]

        if action == "navigate" and len(args) >= 3:
            await cmd_navigate(session_id, args[2])
        elif action == "snapshot":
            selector = args[2] if len(args) >= 3 else None
            await cmd_snapshot(session_id, selector)
        elif action == "click" and len(args) >= 3:
            await cmd_click(session_id, args[2])
        elif action == "type" and len(args) >= 4:
            await cmd_type(session_id, args[2], args[3])
        elif action == "hover" and len(args) >= 3:
            await cmd_hover(session_id, args[2])
        elif action == "select" and len(args) >= 4:
            await cmd_select_option(session_id, args[2], args[3])
        elif action == "press" and len(args) >= 3:
            await cmd_press_key(session_id, args[2])
        elif action == "screenshot":
            selector = None
            output = None
            i = 2
            while i < len(args):
                if args[i] in ("-o", "--output") and i + 1 < len(args):
                    output = args[i + 1]
                    i += 2
                elif args[i] and not args[i].startswith("-"):
                    selector = args[i]
                    i += 1
                else:
                    i += 1
            await cmd_screenshot(session_id, selector, output)
        elif action == "back":
            await cmd_go_back(session_id)
        elif action == "forward":
            await cmd_go_forward(session_id)
        elif action == "delete":
            await cmd_delete(session_id)
        else:
            print(f"Unknown action or missing args: {action}", file=sys.stderr)
            sys.exit(1)
    else:
        print("Invalid command", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
