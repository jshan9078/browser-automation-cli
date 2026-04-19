# Browser CLI

> **If you are an LLM, see [AGENTS.md](./AGENTS.md) for quick setup instructions.**

---

## If you are a human

### Install

Preferred (published package):

```bash
pipx install browser-cli
browser install
```

Without publishing (install directly from Git):

```bash
pipx install "git+https://github.com/<your-org>/<your-repo>.git"
browser install
```

From a local checkout:

```bash
bash ./setup.sh
```

Manual dev install (fallback):

```bash
pip install -e .
browser install
```

### Start the daemon

In a terminal:

```bash
browser-daemon
```

A browser window will open. Keep this running.

### Create a session

In another terminal:

```bash
browser create
```

This opens a fresh browser window. Manually log into any sites you need (GitHub, Jira, etc.).

### Run browser actions

```bash
# Navigate to a site
browser <session_id> navigate github.com/user/repo

# Get page elements
browser <session_id> snapshot

# Click an element
browser <session_id> click ".readme"

# Take a screenshot
browser <session_id> screenshot

# Type text
browser <session_id> type "input[name=search]" "query"
```

### List active sessions

```bash
browser list
```

### Delete a session

```bash
browser delete <session_id>
```

### Stop the daemon

Press `Ctrl+C` in the terminal running `browser-daemon`.

---

## Commands Reference

### Standalone (No Daemon)

**Capture Command:**

Uses JPEG format for efficient file sizes (~10x smaller than PNG).

```bash
browser capture <url> [options]
```

**Options:**
- `-f, --full-page` - Capture full scrollable page (default: viewport only)
- `-o, --output <path>` - Custom output path

**Examples:**
```bash
# Quick viewport screenshot (fastest, smallest file)
browser capture https://example.com

# Full page screenshot
browser capture https://example.com -f

# Save to custom location
browser capture https://example.com -o ./my-screenshot.jpg

# Full page + custom path
browser capture https://example.com -f -o ./full-page.jpg

# Capture localhost
browser capture http://localhost:3000
browser capture http://127.0.0.1:8080/dashboard
```

### Daemon Commands

| Command | Description |
|---------|-------------|
| `browser install` | Install Chromium runtime |
| `browser create` | Create new session (opens browser for login) |
| `browser list` | List active sessions |
| `browser <id> navigate <url>` | Navigate to URL |
| `browser <id> snapshot [selector]` | Get page elements |
| `browser <id> click <selector>` | Click element |
| `browser <id> type <selector> <text>` | Type text |
| `browser <id> hover <selector>` | Hover element |
| `browser <id> select <selector> <value>` | Select dropdown option |
| `browser <id> press <key>` | Press keyboard key |
| `browser <id> screenshot [selector]` | Take screenshot |
| `browser <id> back` | Go back |
| `browser <id> forward` | Go forward |
| `browser <id> delete` | Delete session |

## Troubleshooting

**"Command not found: browser" or "browser: command not found"**

If `pipx install` succeeded but commands aren't found, your shell may not have `~/.local/bin` in PATH:

```bash
# Quick fix (current session only)
export PATH="$HOME/.local/bin:$PATH"

# Permanent fix (add to shell config)
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc  # or ~/.bashrc
source ~/.zshrc  # apply immediately
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
