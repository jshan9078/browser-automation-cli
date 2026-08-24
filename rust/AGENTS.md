# Agent Integration Guide

> **Give [SKILL.md](./SKILL.md) to your coding agent harness as a skill file. It contains ready-to-use workflows and decision guides for this tool.**

## What This Tool Does

Browser CLI provides authenticated browser automation via a CLI:
- **`browser-daemon`** — background process owning a headless Chromium and persistent sessions, reachable over a Unix socket
- **`browser`** — CLI client (~2 ms per call) that sends commands to the daemon, or runs standalone captures

Any coding agent can use it via subprocess calls. No SDK required.

## Install

```bash
uv tool install browser-automation-cli
browser install
```

If `browser` or `browser-daemon` is not found: `export PATH="$HOME/.local/bin:$PATH"`

## Quick Start

```bash
browser-daemon &                 # 1. start once; headless, nothing opens
browser create                   # 2. prints an 8-char session id, e.g. abc12345
browser abc12345 navigate https://github.com/login
browser abc12345 snapshot        # 3. see what is on the page
browser abc12345 type --label "Username or email address" octocat
browser abc12345 click --text "Sign in" -s     # -s: return a fresh snapshot with the result
```

If a site needs the **user** to log in: `browser abc12345 show` (a window opens), ask the user to log in, then `browser abc12345 hide`. Never ask for credentials.

## Session Model

| Property | Detail |
|----------|--------|
| **ID** | 8-char hex (`a1b2c3d4`) |
| **Scope** | One session = one isolated browser profile (cookies, storage). One session can visit many sites |
| **Persistence** | Sessions survive daemon restarts (state saved under `~/.browser-daemon/sessions/`). `delete` forgets them |
| **Idle** | Hidden sessions are frozen (scripts paused) after 10 s idle and hibernated after 10 min; both are transparent — just send the next command |
| **Visibility** | Headless by default. `create --show`, `show`, `hide` move a session between a window and headless, keeping auth |
| **Viewport** | 1280x800 desktop; `navigator.webdriver` hidden; UA matches the real Chromium version |

## Command Reference

### Standalone (no daemon)

```bash
browser capture <url> [-f] [-o path]   # headless JPEG screenshot (viewport; -f full page)
browser install [--headless-only]      # download Chromium (Chrome for Testing; ~550 MB, half with --headless-only)
browser cleanup                        # kill Chromium processes launched by this tool
browser --version | update             # show version / upgrade (daily PyPI check; BROWSER_NO_UPDATE_CHECK=1 disables)
browser docs skill|agents              # print the skill file / this guide (also shipped in the binary)
```

### Sessions

```bash
browser create [--show]      # new session (id on stdout)
browser list [--table]       # JSON: [{session_id, url, title, state, visible}]
browser <id> show | hide     # window <-> headless
browser <id> delete
browser shutdown
```

### Page commands

Every command prints JSON and exits 1 on failure; `snapshot` prints text. Add `-s`/`--snapshot` to any action to append a fresh snapshot.

| Command | Notes |
|---------|-------|
| `navigate <url> [--wait load\|domcontentloaded\|networkidle]` | Returns when the page is usable (`load`). A slow `networkidle` is reported as `settled: false`, not an error |
| `snapshot [scope-selector] [--all] [--max N] [--json]` | Visible interactive elements and headings, one per line |
| `click <target> [--double]` | |
| `type <target> <text> [--sequential] [--submit]` | alias `fill`; `--sequential` for autocomplete/combobox inputs; `--submit` presses Enter after |
| `press <key> [target]` | `Enter`, `Tab`, `Escape`, `Control+a` |
| `hover <target>` | |
| `select <target> <value-or-label>` | |
| `scroll [up\|down] [px]` / `scroll <target>` | |
| `text [selector]` | Readable text — use for extraction instead of `snapshot --all` |
| `wait [--text T \| --selector S] [--gone] [--timeout ms]` | |
| `screenshot [target] [-o path] [-f] [-q 70]` | JPEG under `~/.browser-daemon/shots/` (mode 600) |
| `eval <js-expression>` | |
| `console [--clear]` | Buffered console messages |
| `back` / `forward` | |
| `batch` | JSON lines on stdin, one round-trip, stops at first failure |

### Targets

| Form | Example |
|------|---------|
| ref from snapshot (**preferred**) | `click @e12` |
| visible text | `click --text "Create"` or `click text=Create` |
| ARIA role + name | `click --role button --name Create` or `click "role=button[name=Create]"` |
| form label / placeholder | `type --label "Email" me@x.com`, `type --placeholder Search foo` |
| CSS / Playwright selector | `click "#submit"`, `click "form >> text=Save"` |

Ambiguous CSS selectors are **refused** (`strict mode violation`) rather than clicking the first match — use a ref or text.

## Reading a snapshot

```
url: https://dash.cloudflare.com/login
title: Cloudflare Dashboard | Manage Your Account
scroll: 0/1400 (viewport 1280x800; [below]/[above] = outside viewport)
@e2 link "Sign up" href="/sign-up"
h1 "Sign in to Cloudflare"
@e7 textbox "Email"
@e8 textbox "Password" type="password"
@e10 checkbox "Save email and login method on this device" [checked=false]
@e11 button "Sign in" [disabled]
@e30 button "Create" [below]
```

- Elements inside same-origin iframes (marked `[frame]`) and open shadow DOM appear in the snapshot and are targeted like any other element.
- `@eN` refs stay valid until the page navigates or the element is removed; a stale ref returns `ref @eN is unknown or stale` — run `snapshot` again.
- `[below]`/`[above]` elements exist but are outside the viewport; clicking them scrolls automatically.
- Hidden elements (`display:none`, `aria-hidden`, zero size) are omitted. `--all` adds paragraphs/list items; `--json` adds `box` (x, y, w, h) and a unique CSS `selector`.
- Large pages: scope with a selector (`snapshot "#main"`) or `--max`.

## Agent Workflow

1. `browser list` — reuse an existing session if one fits.
2. `browser create` if needed (`--show` only when the user must log in).
3. `navigate <url> -s` — one call gives you the page and its snapshot.
4. Act with refs/text: `type @e7 user@x.com`, `click --text "Sign in" -s`.
5. Verify from the returned snapshot or `text`; take a `screenshot` only when layout matters.
6. Chain known steps with `batch` to save round-trips:
   ```bash
   printf '%s\n' '{"cmd":"type @e7 me@x.com"}' '{"cmd":"type @e8 secret --submit"}' '{"cmd":"snapshot"}' | browser abc12345 batch
   ```

## Output Parsing

```json
{"success": true, "url": "https://...", "title": "..."}
{"success": false, "error": "strict mode violation: locator(\"button.flex\") resolved to 3 elements"}
```

`snapshot --json` elements: `{ref, role, name, pos, box, href?, value?, placeholder?, checked?, options?, expanded?, selected?, disabled?, required?}`.

### Calling from code

```python
import subprocess, json
r = subprocess.run(["browser", "abc12345", "click", "--text", "Create", "-s"], capture_output=True, text=True)
snapshot_text = r.stdout            # success: snapshot text; failure: JSON with "error", exit code 1
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Daemon not running` | Start `browser-daemon` |
| `Session not found` | `browser list` |
| `ref @eN is unknown or stale` | `snapshot` again |
| `strict mode violation` | Use `@ref`, `--text`, or a tighter selector |
| `… is covered by <el> …` | An overlay blocks the click — dismiss it, then retry |
| `Timeout … waiting for locator` | Element not visible/enabled — `snapshot` to check state, `wait --text …` |
| Site shows a login page | `browser <id> show`, ask the user to log in, `hide` |
| Browser doesn't launch | `browser install` |

## Key Rules for Agents

1. **Never request credentials** — the user logs in manually in a shown window.
2. **Check `success`** (or the exit code) before proceeding.
3. **Prefer refs and text targets** over guessed CSS selectors.
4. **Use `-s` and `batch`** to cut round-trips; use `text` for extraction.
5. **Reuse sessions**; delete them when no longer needed.
6. **Leave the daemon running** between actions.
