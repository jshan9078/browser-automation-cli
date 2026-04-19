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

Before using commands, ensure the environment is ready:

1. Install dependencies (one-time):
```bash
pipx install browser-cli

# If commands not found, add to PATH:
# export PATH="$HOME/.local/bin:$PATH"

browser install
```

If not published yet:
```bash
pipx install "git+https://github.com/<your-org>/<your-repo>.git"
browser install
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
- One session can visit multiple different sites (including localhost URLs).
- Multiple agents can share the same session ID.
- Multiple sessions can run at once for different accounts/workflows.

## Command Usage

Standalone command (no daemon, no session, headless):

```bash
# Viewport screenshot (fastest, default)
browser capture <url>

# Full page screenshot
browser capture <url> -f

# Custom output path
browser capture <url> -o ./screenshot.jpg

# Combined
browser capture <url> -f -o ./full-page.jpg
```

Daemon commands (requires session, interactive browser):

```bash
browser create
browser list
browser <session_id> navigate <url>
browser <session_id> snapshot [selector]
browser <session_id> click <selector>
browser <session_id> type <selector> <text>
browser <session_id> hover <selector>
browser <session_id> select <selector> <value>
browser <session_id> press <key>
browser <session_id> screenshot [selector]
browser <session_id> back
browser <session_id> forward
browser delete <session_id>
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

Example action response:
```json
{
  "success": true,
  "url": "http://localhost:3000/dashboard",
  "title": "Dashboard"
}
```

Example snapshot response:
```json
{
  "success": true,
  "elements": [
    {"ref": "el_0", "tag": "button", "text": "Save"},
    {"ref": "el_1", "tag": "input", "name": "email", "placeholder": "you@example.com"}
  ]
}
```

## Selector Guidance

- Prefer stable CSS selectors (`name`, `data-*`, role-oriented classes).
- Use `snapshot` first to discover elements before clicking/typing.
- Quote selectors containing special characters.

## Operational Rules

- Do not request credentials; user authenticates manually in browser UI.
- Reuse session IDs when possible to preserve auth and reduce friction.
- Delete sessions when no longer needed to keep state clean.

## Quick Troubleshooting

- `Daemon not running` -> start `browser-daemon`.
- `Session not found` -> run `browser list` and use a valid ID.
- `Element not found` -> run `browser <id> snapshot` and update selector.
