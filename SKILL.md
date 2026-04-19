---
name: browser-cli
description: Use a local browser daemon plus CLI to run authenticated, multi-session browser automation for any coding agent.
license: Complete terms in LICENSE.txt
---

This skill enables an agent to control a local Playwright browser through `browser` and `browser-daemon` commands. Use it for navigation, snapshots, form interactions, and screenshots on authenticated sites, including localhost apps.

The user may ask for UI checks, web automation, scraping, login-required workflows, or multi-site workflows across one or more agent sessions.

## When To Use

Use this skill when tasks involve browser interactions such as:
- Capturing screenshots for verification for frontend development
- Clicking through flows, filling forms, and pressing keys
- Visiting websites or localhost apps and extracting information
- Working on sites that require manual user login

## Decision Guide: Which Command to Use?

**Use `browser capture` (standalone) when:**
- You only need a screenshot, no interaction
- The site doesn't require authentication (public or localhost)
- You want the fastest possible result
- No daemon setup is needed

**Use daemon commands when:**
- You need to click, type, or navigate through pages
- The site requires authentication
- You need to extract page elements/structure
- You want to reuse a logged-in session

## Quick Capture (No Setup Required)

For simple one-off screenshots without authentication or daemon setup:

```bash
# Quick viewport screenshot (default - fastest, smallest file)
browser capture https://example.com

# Full page screenshot
browser capture https://example.com -f

# Custom output path
browser capture https://example.com -o ./screenshot.jpg

# Local development server
browser capture http://localhost:3000

# Returns: {"success": true, "path": "/tmp/browser_capture_1234567890.jpg", "format": "jpeg"}
```

**Features:**
- **JPEG format** - Efficient compression (~10x smaller than PNG)
- **Viewport by default** - Fastest capture of visible area only
- **Full-page option** - Use `-f` flag for entire scrollable page
- Headless execution - No browser window shown
- No daemon required - Direct Playwright execution

**Options:**
- `-f, --full-page` - Capture full scrollable page (default: viewport only)
- `-o, --output <path>` - Custom output path instead of /tmp

**This is the optimal choice when:**
- You only need a screenshot, no interaction
- The site doesn't require authentication (public or localhost)
- You want the fastest possible result
- No daemon setup is needed

**Performance tip:** Default viewport capture is significantly faster and produces smaller files than full-page. Use `-f` only when you need the entire page.

## Setup Checklist

Before using daemon commands, ensure the environment is ready:

1. Install (one-time):
```bash
uv tool install browser-automation-cli
browser install
```

If commands are not found:
```bash
export PATH="$HOME/.local/bin:$PATH"
```

2. Start daemon (must remain running):
```bash
browser-daemon
```

3. Create a session for authentication:
```bash
browser create
```

4. Ask user to complete manual login in the opened browser window.

## Session Model

- A session is one persistent browser context with cookies/auth state.
- Session IDs are 8-character hex strings (e.g., `a1b2c3d4`).
- One session can visit multiple different sites (including localhost URLs).
- Multiple agents can share the same session ID.
- Multiple sessions can run at once for different accounts/workflows.
- Sessions persist until explicitly deleted or the daemon stops.
- Viewport is forced to 1920x1080 desktop. `navigator.webdriver` is hidden.

## Command Reference

### Standalone (no daemon, no session)

```bash
browser capture <url> [-f] [-o <path>]
```

### Daemon Commands

```bash
# Session management
browser install                       # Install Chromium runtime
browser cleanup                       # Kill stale Chrome processes
browser create                        # Create session (opens browser for login)
browser list                          # List active sessions
browser delete <session_id>           # Delete session

# Page actions (require session_id)
browser <id> navigate <url>           # Navigate to URL
browser <id> snapshot [selector]      # Get page elements with CSS selectors
browser <id> click <selector>         # Click element
browser <id> type <selector> <text>   # Type text into input
browser <id> hover <selector>         # Hover element
browser <id> select <selector> <val>  # Select dropdown option
browser <id> press <key>              # Press keyboard key (Enter, Tab, etc.)
browser <id> screenshot [sel] [-o p]  # Screenshot page or element
browser <id> back                     # Go back
browser <id> forward                  # Go forward
browser <id> delete                   # Delete session
```

## Agent Workflow

Use this sequence for reliable execution:

1. Check existing sessions:
```bash
browser list
```

2. Reuse a suitable session ID, or create one:
```bash
browser create
```

3. Navigate and inspect:
```bash
browser <id> navigate http://localhost:3000
browser <id> snapshot
```

4. Interact based on snapshot output:
```bash
browser <id> click "button[type=submit]"
browser <id> type "input[name=email]" "user@example.com"
```

5. Verify state:
```bash
browser <id> screenshot
browser <id> snapshot
```

## Output Contract

Commands return JSON. Always check `success` first.

### Navigate / Click / Back / Forward
```json
{
  "success": true,
  "url": "http://localhost:3000/dashboard",
  "title": "Dashboard"
}
```

### Snapshot
```json
{
  "success": true,
  "url": "http://localhost:3000",
  "title": "App",
  "scrollY": 0,
  "viewportHeight": 1080,
  "documentHeight": 2400,
  "elements": [
    {
      "ref": "el_0",
      "tag": "button",
      "selector": "button.submit-btn",
      "text": "Save",
      "interactive": true,
      "href": null,
      "name": null,
      "placeholder": null,
      "ariaLabel": null
    },
    {
      "ref": "el_1",
      "tag": "input",
      "selector": "input[name=email]",
      "text": null,
      "interactive": true,
      "href": null,
      "name": "email",
      "placeholder": "you@example.com",
      "ariaLabel": null
    }
  ]
}
```

### Screenshot
```json
{
  "success": true,
  "path": "/tmp/browser_screenshot_1234567890.jpg",
  "format": "jpeg"
}
```

### Error
```json
{
  "success": false,
  "error": "Session abc12345 not found"
}
```

## Selector Guidance

- **Always run `snapshot` first** to discover elements and their selectors.
- Prefer stable CSS selectors (`id`, `name`, `data-*`, role-oriented classes).
- Use `snapshot` output `selector` field directly — it is pre-built for each element.
- Quote selectors containing special characters.
- Text-based matching: `"a:has-text('Sign In')"`

## Shell Integration

Agents can call the CLI via subprocess:

```python
import subprocess, json
result = subprocess.run(["browser", "abc12345", "snapshot"], capture_output=True, text=True)
data = json.loads(result.stdout)
```

```typescript
import { execSync } from 'child_process';
const data = JSON.parse(execSync('browser abc12345 snapshot').toString());
```

## Operational Rules

- Do not request credentials; user authenticates manually in browser UI.
- Reuse session IDs when possible to preserve auth and reduce friction.
- Delete sessions when no longer needed to keep state clean.
- The daemon must remain running between actions.
- Always check `success` in JSON output before proceeding to the next step.

## Quick Troubleshooting

- `Daemon not running` -> start `browser-daemon`.
- `Session not found` -> run `browser list` and use a valid ID.
- `Element not found` -> run `browser <id> snapshot` and update selector.
- `Command not found` -> `export PATH="$HOME/.local/bin:$PATH"`.
- Stale Chrome processes -> run `browser cleanup`.
