# Browser CLI

> **If you are an LLM, see [AGENTS.md](./AGENTS.md) for quick setup and usage instructions.**

A lightweight, self-hosted browser automation tool with a background daemon and CLI client. Enables authenticated web automation, screenshots, DOM snapshots, and page interactions via simple CLI commands. Share a `SKILL.md` file with your coding agent harness for seamless integration.

## Install

```bash
pipx install browser-cli
browser install
```

If commands are not found after install, add `~/.local/bin` to your PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Quick Start

### 1. Start the daemon

```bash
browser-daemon
```

A browser window will open. Keep this terminal running.

### 2. Create a session

```bash
browser create
```

This opens a fresh browser window. Manually log into any sites you need (GitHub, Jira, etc.).

### 3. Run browser actions

```bash
# Navigate to a site
browser <session_id> navigate https://github.com

# Get page elements and their CSS selectors
browser <session_id> snapshot

# Click an element using a CSS selector
browser <session_id> click "button.login-btn"

# Type text into an input
browser <session_id> type "input[name=search]" "query"

# Take a screenshot (JPEG, saved to /tmp)
browser <session_id> screenshot
```

### 4. Manage sessions

```bash
browser list          # List active sessions
browser delete <id>   # Delete a session
```

### 5. Stop the daemon

Press `Ctrl+C` in the terminal running `browser-daemon`.

---

## Commands Reference

### Standalone (No Daemon Required)

Quick screenshot capture using headless Playwright. Uses JPEG format for efficient file sizes.

```bash
browser capture <url> [options]
```

**Options:**
| Flag | Description |
|------|-------------|
| `-f, --full-page` | Capture full scrollable page (default: viewport only) |
| `-o, --output <path>` | Custom output path |

**Examples:**
```bash
browser capture https://example.com
browser capture https://example.com -f
browser capture https://example.com -o ./screenshot.jpg
browser capture http://localhost:3000
```

### Daemon Commands

Requires `browser-daemon` running and an active session.

| Command | Description |
|---------|-------------|
| `browser install` | Install Chromium runtime |
| `browser cleanup` | Kill stale Chrome processes |
| `browser create` | Create new session (opens browser for login) |
| `browser list` | List active sessions |
| `browser <id> navigate <url>` | Navigate to URL |
| `browser <id> snapshot [selector]` | Get page elements with CSS selectors |
| `browser <id> click <selector>` | Click element |
| `browser <id> type <selector> <text>` | Type text into input |
| `browser <id> hover <selector>` | Hover element |
| `browser <id> select <selector> <value>` | Select dropdown option |
| `browser <id> press <key>` | Press keyboard key |
| `browser <id> screenshot [selector] [-o <path>]` | Take screenshot (full page or element) |
| `browser <id> back` | Go back |
| `browser <id> forward` | Go forward |
| `browser <id> delete` | Delete session |

---

## Architecture

- **Daemon** (`browser-daemon`): Unix socket server managing persistent Playwright browser contexts. Each session is an isolated browser context with cookies/auth state.
- **CLI** (`browser`): Sends commands to the daemon via Unix socket, or runs standalone capture directly via Playwright.
- **Session model**: One session = one authenticated browser context. Sessions persist until deleted. Multiple sessions can run in parallel. Multiple agents can share the same session ID.

## Anti-Detection

- `navigator.webdriver` hidden via `add_init_script`
- Explicit desktop Chrome user agent
- 1920x1080 viewport to avoid mobile layouts

## Output Format

All commands return JSON. Check `success` field first.

**Action response:**
```json
{
  "success": true,
  "url": "https://github.com",
  "title": "GitHub"
}
```

**Snapshot response:**
```json
{
  "success": true,
  "url": "https://github.com",
  "title": "GitHub",
  "scrollY": 0,
  "viewportHeight": 1080,
  "documentHeight": 2400,
  "elements": [
    {
      "ref": "el_0",
      "tag": "a",
      "selector": "a.header-link",
      "text": "Pull requests",
      "interactive": true,
      "href": "https://github.com/pulls",
      "ariaLabel": null
    }
  ]
}
```

**Screenshot response:**
```json
{
  "success": true,
  "path": "/tmp/browser_screenshot_1234567890.jpg",
  "format": "jpeg"
}
```

---

## Using with Coding Agents

Share the `SKILL.md` file with your coding agent harness. It contains agent-specific instructions, workflow patterns, and decision guides for when to use standalone vs daemon commands.

See [AGENTS.md](./AGENTS.md) for complete agent integration guide.

## Troubleshooting

**"Command not found: browser"**

```bash
export PATH="$HOME/.local/bin:$PATH"
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

**"Daemon not running"**

```bash
browser-daemon
```

**Browser doesn't open**

```bash
browser install
```

**Session not found**

```bash
browser list
```

**Stale Chrome processes**

```bash
browser cleanup
```
