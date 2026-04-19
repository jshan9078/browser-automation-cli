# Agent Integration Guide

> **Give [SKILL.md](./SKILL.md) to your coding agent harness as a skill file. It contains ready-to-use workflows and decision guides for this tool.**

## What This Tool Does

Browser CLI provides authenticated browser automation via a CLI. It consists of:
- **`browser-daemon`** — background process managing persistent browser sessions via Unix socket
- **`browser`** — CLI client that sends commands to the daemon, or runs standalone captures

Any coding agent can use it via subprocess calls. No SDK required.

## Install

```bash
pipx install browser-cli
browser install
```

If `browser` or `browser-daemon` is not found:
```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Quick Start

### 1. Start daemon (must stay running)
```bash
browser-daemon
```
A visible browser window opens. The daemon must remain running for all session commands.

### 2. Create session
```bash
browser create
```
Returns an 8-character hex session ID (e.g., `abc12345`). A fresh browser window opens — the user logs in manually.

### 3. Use the session
```bash
browser abc12345 navigate https://github.com
browser abc12345 snapshot
browser abc12345 click "a.header-link"
browser abc12345 screenshot
```

## Session Model

| Property | Detail |
|----------|--------|
| **ID format** | 8-char hex string (e.g., `a1b2c3d4`) |
| **Scope** | One session = one isolated browser context with its own cookies/auth |
| **Persistence** | Sessions live until explicitly deleted or daemon stops |
| **Sharing** | Multiple agents/calls can use the same session ID |
| **Parallelism** | Multiple sessions can run simultaneously |
| **Viewport** | 1920x1080 desktop (anti-detection: hides `navigator.webdriver`, sets desktop Chrome UA) |

## Command Reference

### Standalone (no daemon, no session)

```bash
browser capture <url> [options]
```

| Flag | Description |
|------|-------------|
| `-f, --full-page` | Full scrollable page (default: viewport only) |
| `-o, --output <path>` | Custom output path (default: `/tmp/browser_capture_<timestamp>.jpg`) |

**Output:** `{"success": true, "path": "/tmp/...", "format": "jpeg"}`

### Daemon Commands

| Command | Description | Output |
|---------|-------------|--------|
| `browser install` | Install Chromium runtime | — |
| `browser cleanup` | Kill stale Chrome processes | — |
| `browser create` | Create session, opens browser | Session ID |
| `browser list` | List active sessions | Table of sessions |
| `browser <id> navigate <url>` | Navigate to URL | `{success, url, title}` |
| `browser <id> snapshot [selector]` | Get elements with CSS selectors | `{success, elements[], scrollY, viewportHeight, documentHeight}` |
| `browser <id> click <selector>` | Click element | `{success, url, title}` |
| `browser <id> type <selector> <text>` | Fill input | `{success}` |
| `browser <id> hover <selector>` | Hover element | `{success}` |
| `browser <id> select <selector> <value>` | Select dropdown option | `{success}` |
| `browser <id> press <key>` | Press keyboard key (e.g., `Enter`, `Tab`) | `{success}` |
| `browser <id> screenshot [selector] [-o <path>]` | Screenshot page or element | `{success, path, format}` |
| `browser <id> back` | Go back | `{success, url, title}` |
| `browser <id> forward` | Go forward | `{success, url, title}` |
| `browser <id> delete` | Delete session | — |
| `browser delete <id>` | Delete session (alternate syntax) | — |

## Agent Workflow

Follow this sequence for reliable execution:

### Step 1: Check for existing sessions
```bash
browser list
```
Reuse an existing session if available. Only create a new one if needed.

### Step 2: Create session (if none exists)
```bash
browser create
```
Wait for the user to complete manual login. The session ID is printed to stdout.

### Step 3: Navigate and inspect
```bash
browser <id> navigate <url>
browser <id> snapshot
```
Parse the snapshot JSON to discover elements, their CSS selectors, text content, and whether they are interactive.

### Step 4: Interact
Use selectors from the snapshot output:
```bash
browser <id> click "button[type=submit]"
browser <id> type "input[name=email]" "user@example.com"
browser <id> press "Enter"
```

### Step 5: Verify
```bash
browser <id> screenshot
browser <id> snapshot
```
Confirm the action succeeded by checking the new page state.

## Output Parsing

**Every command returns JSON on stdout.** Always parse and check `success` before proceeding.

### Navigate / Click / Back / Forward
```json
{"success": true, "url": "https://...", "title": "..."}
```

### Snapshot
```json
{
  "success": true,
  "url": "https://...",
  "title": "...",
  "scrollY": 0,
  "viewportHeight": 1080,
  "documentHeight": 2400,
  "elements": [
    {
      "ref": "el_0",
      "tag": "button",
      "selector": "button.submit-btn",
      "text": "Submit",
      "interactive": true,
      "href": null,
      "name": null,
      "placeholder": null,
      "ariaLabel": null
    }
  ]
}
```

### Screenshot
```json
{"success": true, "path": "/tmp/browser_screenshot_1234567890.jpg", "format": "jpeg"}
```

### Error
```json
{"success": false, "error": "Session abc12345 not found"}
```

## Calling from Code

### Python
```python
import subprocess, json

result = subprocess.run(["browser", "abc12345", "snapshot"], capture_output=True, text=True)
data = json.loads(result.stdout)
if data["success"]:
    elements = data["elements"]
```

### TypeScript / Node.js
```typescript
import { execSync } from 'child_process';

const output = execSync('browser abc12345 snapshot');
const data = JSON.parse(output.toString());
if (data.success) {
    const elements = data.elements;
}
```

### Shell
```bash
response=$(browser abc12345 snapshot)
echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['success'])"
```

## Selector Guidance

- **Always run `snapshot` first** to discover available elements and their selectors
- Prefer stable selectors: `id`, `name`, `data-testid`, role-oriented classes
- Quote selectors with special characters: `"input[name='user[email]']"`
- Use `:has-text()` for text-based matching: `"a:has-text('Sign In')"`
- The snapshot output provides a `selector` field for each element — use it directly

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Daemon not running` | Start `browser-daemon` |
| `Session not found` | Run `browser list` to find valid IDs |
| `Element not found` | Run `browser <id> snapshot` to get current selectors |
| `Command not found` | `export PATH="$HOME/.local/bin:$PATH"` |
| Browser doesn't open | Run `browser install` |
| Stale Chrome processes | Run `browser cleanup` |
| Connection refused | Kill existing daemon, restart `browser-daemon` |

## Key Rules for Agents

1. **Never request credentials** — user authenticates manually in the browser UI
2. **Always check `success`** in JSON output before proceeding
3. **Reuse session IDs** when possible to preserve auth state
4. **Run `snapshot` before `click`/`type`** to discover current page elements
5. **Delete sessions** when no longer needed
6. **The daemon must stay running** — do not kill it between actions
