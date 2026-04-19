# Agent Setup Guide

> **For agent integration, see [SKILL.md](./SKILL.md) for usage patterns. Add the SKILL.md to your local setup as part of your skills configuration.**

This document explains how to set up Browser CLI for users and integrate it into your agent workflow.

## Setup (One-time)

Preferred setup (published package):

```bash
pipx install browser-cli

# If "command not found" after install:
# export PATH="$HOME/.local/bin:$PATH"

browser install
```

If package is not published yet (install from Git):

```bash
pipx install "git+https://github.com/<your-org>/<your-repo>.git"
browser install
```

From local checkout (developer path):

```bash
bash ./setup.sh
```

## Starting the Daemon

The daemon must be running before any browser actions work. Start it with:

```bash
browser-daemon
```

**Important:** The daemon opens a visible browser window. It must remain running.

## Session Lifecycle

1. **Create session** - User manually logs into sites:
   ```bash
   browser create
   ```

2. **Use session** - Agent performs actions:
   ```bash
   browser <session_id> navigate github.com/user/repo
   browser <session_id> snapshot
   ```

3. **Share session** - Multiple agents can use the same session ID

4. **Delete when done**:
   ```bash
   browser delete <session_id>
   ```

## Agent Workflow Example

```bash
# 1. Create session, user logs in manually
browser create
# → returns session_id like "abc12345"

# 2. Navigate and inspect
browser abc12345 navigate github.com/user/repo
browser abc12345 snapshot
# → returns elements array

# 3. Interact
browser abc12345 click "button.submit"
browser abc12345 type "input[name=message]" "Hello"
browser abc12345 screenshot

# 4. Agent parses JSON output to decide next steps
```

## Output Format

All actions return JSON:
```json
{
  "success": true,
  "url": "https://github.com/user/repo",
  "title": "Repository"
}
```

For `snapshot`:
```json
{
  "success": true,
  "elements": [
    {"ref": "el_0", "tag": "a", "text": "README", "href": "..."},
    {"ref": "el_1", "tag": "button", "text": "Submit", "name": null}
  ]
}
```

For `screenshot`:
```json
{
  "success": true,
  "image": "base64encodedstring..."
}
```

## Shell Integration

Agents can call the CLI via subprocess. Example patterns:

```python
import subprocess
import json

result = subprocess.run(
    ["browser", "abc12345", "snapshot"],
    capture_output=True,
    text=True
)
data = json.loads(result.stdout)
```

```typescript
import { execSync } from 'child_process';

const output = execSync(`browser abc12345 snapshot`);
const data = JSON.parse(output.toString());
```

## Sharing Sessions Between Agents

Sessions persist until explicitly deleted. Multiple agents can reference the same session:

```bash
# Agent A creates session
browser create
# → abc12345

# Agent B uses same session
browser abc12345 navigate github.com
```

## Key Points

- Daemon runs once, handles multiple sessions
- User manually authenticates (no credentials in code)
- Session IDs are 8-character hex strings
- Browser window stays open for the session duration
- Actions are blocking (not parallel within a session)
