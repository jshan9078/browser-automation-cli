# Browser Automation CLI

> **If you are an LLM, see** **[AGENTS.md](https://github.com/jshan9078/browser-automation-cli/blob/main/AGENTS.md)** **for quick setup and usage instructions.**

A lightweight, self-hosted browser automation tool with a background daemon and CLI client. Enables authenticated web automation, screenshots, compact page snapshots, and page interactions via simple CLI commands. Share the [`SKILL.md`](https://github.com/jshan9078/browser-automation-cli/blob/main/SKILL.md) file with your coding agent harness for seamless integration.

## Why This Exists

Coding agents need to interact with authenticated web apps. Existing solutions all have tradeoffs:

* **Chrome DevTools MCP** — requires Node.js, per-agent MCP server configuration, Google telemetry by default, and complex setup for each coding agent
* **BrowserMCP and similar tools** — require installing Chrome extensions, tie into specific ecosystems, and use MCP which bloats the agent's context window with tool definitions and protocol overhead
* **Playwright/Puppeteer scripts** — require writing code for every interaction, no persistent auth state
* **AI browser frameworks** — heavy, opinionated, and framework-locked

Browser CLI solves this with a persistent daemon that any agent can call via subprocess. No extensions, no MCP config, no SDKs, no ecosystem lock-in. Sessions persist across agent calls (and daemon restarts) so you only log in once.

## Install

```bash
uv tool install browser-automation-cli
browser install
```

If commands are not found after install, add `~/.local/bin` to your PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Quick Start

### 1. Start the daemon

```bash
browser create   # the daemon auto-starts on first use (0.5.0+)
```

Nothing visible opens: the daemon runs Chromium headless in the background. Run it yourself with `browser daemon` (or the legacy `browser-daemon` alias) if you prefer; `BROWSER_NO_AUTOSTART=1` disables auto-start.

### 2. Create a session

```bash
browser create            # headless session
browser create --show     # opens a window so you can log in; `browser <id> hide` afterwards
```

A session is an isolated browser profile (cookies, storage). Log into any sites you need while it is shown; the agent can drive it hidden afterwards. Sessions survive daemon restarts.

### 3. Run browser actions

```bash
browser <id> navigate https://github.com
browser <id> snapshot                      # interactive elements, one line each, with @refs
browser <id> click @e7                     # click by ref from the snapshot
browser <id> click --text "Sign in"        # or by visible text / role / label
browser <id> type --label "Username" octocat
browser <id> screenshot                    # JPEG saved under ~/.browser-daemon/shots/
```

A snapshot looks like this (Cloudflare login, 245 tokens):

```
url: https://dash.cloudflare.com/login
title: Cloudflare Dashboard | Manage Your Account
@e2 link "Sign up" href="/sign-up"
h1 "Sign in to Cloudflare"
@e3 button "Continue with Google"
@e7 textbox "Email"
@e8 textbox "Password" type="password"
@e10 checkbox "Save email and login method on this device"
@e11 button "Sign in" [disabled]
```

### 4. Manage sessions

```bash
browser list                  # JSON (--table for humans)
browser <id> show | hide      # move between a visible window and headless
browser <id> delete
browser shutdown              # stop the daemon; sessions are saved and restored next start
```

***

## Commands Reference

### Standalone (no daemon)

```bash
browser capture <url> [-f] [-o <path>]     # headless viewport screenshot (-f = full page)
browser install                            # download Chromium (~170 MB)
browser cleanup                            # kill Chromium processes launched from Playwright's cache
```

### Sessions

| Command | Description |
| :-- | :-- |
| `browser create [--show]` | New session; `--show` opens a window (for manual login) |
| `browser list [--table]` | Sessions with `state` (active / frozen / hibernated) and `visible` |
| `browser <id> show` / `hide` | Move the session to a visible window / back to headless (auth kept) |
| `browser <id> delete` | Close session and forget its cookies |
| `browser shutdown` | Stop the daemon gracefully |
| `browser --version` / `browser update` | Show version; upgrade to the latest PyPI release. The daemon checks PyPI once a day and the CLI prints a one-line hint on stderr when a newer version exists (`BROWSER_NO_UPDATE_CHECK=1` disables) |

### Page commands

All print JSON (snapshot prints text). Add `-s` / `--snapshot` to any action to get a fresh snapshot in the same call.

| Command | Description |
| :-- | :-- |
| `navigate <url> [--wait load\|domcontentloaded\|networkidle]` | Returns as soon as the page is usable; never fails on a slow `networkidle` |
| `snapshot [scope] [--all] [--max N] [--json]` | Visible interactive elements + headings. `--all` adds text blocks, `--json` gives boxes and unique selectors |
| `click <target> [--double]` | |
| `type <target> <text> [--sequential] [--submit]` | `fill()` by default; `--sequential` sends key events (autocomplete); `--submit` presses Enter |
| `press <key> [target]` | `Enter`, `Tab`, `Control+a`, … |
| `hover <target>` | |
| `select <target> <value-or-label>` | |
| `scroll [up\|down] [px]` / `scroll <target>` | |
| `text [selector]` | Readable text of the page or an element (cheap extraction) |
| `wait [--text T \| --selector S] [--gone] [--timeout ms]` | |
| `screenshot [target] [-o path] [-f] [-q 70]` | JPEG; element screenshots via any target |
| `eval <js>` | Evaluate an expression in the page |
| `console [--clear]` | Buffered console messages |
| `back` / `forward` | |
| `batch` | JSON lines on stdin, run in one round-trip, stop at first failure |

**Targets:** `@e12` (ref from snapshot — preferred) · CSS selector · `text=Create` · `role=button[name=Create]` · `label=Email` · `placeholder=Search` · or flags `--text / --role [--name] / --label / --placeholder`. Ambiguous CSS selectors are refused (strict mode) instead of clicking the first match.

***

## Architecture

* **Daemon** (`browser-daemon`): Unix socket server (`~/.browser-daemon/socket`, mode 600) owning a headless Chromium, plus a headed one that exists only while some session is `show`n.
* **CLI** (`browser`): ~40 ms per call, no Playwright import on the daemon path.
* **Sessions**: one isolated browser context each. Hidden sessions are **frozen** after 10 s idle (script execution paused, ~3% CPU on animated dashboards; callbacks that fire while frozen are dropped, so `BROWSER_FREEZE_AFTER=0` disables it) and **hibernated** to `~/.browser-daemon/sessions/<id>.json` (cookies + storage + URL) after 10 min idle or on shutdown; they are rehydrated transparently on the next command. Tune with `BROWSER_FREEZE_AFTER` / `BROWSER_HIBERNATE_AFTER` (seconds).
* **Resource profile** (M4, Cloudflare dashboard parked in a session): 2% CPU / 1.1 GB vs 264% CPU / 2.1 GB for v0.2. See [AGENTBENCH.md](AGENTBENCH.md) for the measurements.

## Anti-Detection

* `navigator.webdriver` hidden via `add_init_script`
* Desktop Chrome user agent derived from the actual Chromium version
* 1280x800 viewport (desktop layouts; same size Anthropic/OpenAI computer-use tooling targets)

## Output Format

Action responses:

```json
{"success": true, "url": "https://github.com", "title": "GitHub"}
```

Errors (exit code 1):

```json
{"success": false, "error": "ref @e9 is unknown or stale (page changed); run snapshot again"}
```

`snapshot --json`:

```json
{"success": true, "url": "...", "title": "...", "scrollY": 0, "viewportHeight": 800, "viewportWidth": 1280, "documentHeight": 2400,
 "elements": [{"ref": "e3", "role": "button", "name": "Create", "pos": "", "box": [912, 640, 88, 36]}]}
```

## Using with Coding Agents

Share [`SKILL.md`](SKILL.md) with your coding agent harness; see [AGENTS.md](AGENTS.md) for the integration guide.

## Rust implementation (preview)

`rust/` contains a Rust client and daemon with the same CLI and socket protocol — no Python, Playwright or
Node at all: `browser install` downloads the same Chrome-for-Testing build Playwright pins (into the same
cache, so both implementations share it), and `capture` is native too. Per-call overhead 40 ms → 2 ms,
daemon RSS −90 MB, frame- and shadow-DOM-aware snapshots. See AGENTBENCH.md. Published to PyPI as
0.4.0 under the same name (wheels for Linux x86_64/aarch64, macOS arm64/x86_64).

```bash
cd rust && cargo build --release
./target/release/browser-daemon &      # drop-in for the Python daemon
./target/release/browser list
```

## Development

```bash
uv sync
.venv/bin/python -m unittest -v tests/test_cli.py          # end-to-end tests against scratch/bench/site
.venv/bin/python scratch/bench/run.py <label>              # benchmark (latency, tokens, idle CPU/RSS)
.venv/bin/python scratch/bench/compare.py baseline <label>
```

## Troubleshooting

| Symptom | Fix |
| :-- | :-- |
| `Command not found: browser` | `export PATH="$HOME/.local/bin:$PATH"` |
| `Daemon not running` | `browser-daemon` |
| Browser doesn't launch | `browser install` |
| `Session not found` | `browser list` |
| `ref @eN is unknown or stale` | Page changed; run `snapshot` again |
| `strict mode violation` | Selector matched several elements; use an `@ref`, `--text`, or a tighter selector |
| Stale Chromium processes | `browser cleanup` |

### Installing the Rust binaries

```bash
curl -fsSL https://raw.githubusercontent.com/jshan9078/browser-automation-cli/main/rust/install.sh | sh
```

or simply `uv tool install browser-automation-cli` (0.4.0+ wheels are the Rust binaries). The script installs
`browser` and `browser-daemon` into `~/.local/bin` (set `BROWSER_CLI_BIN` to change); other platforms: `cd rust && cargo build --release`.

Wheel (same PyPI project name, so download stats carry over): `cd rust && uvx maturin build --release` →
`uv tool install rust/target/wheels/browser_automation_cli-*.whl`. From 0.4.0 the PyPI package ships
the Rust binaries; the Python implementation remains in `cli/` and `daemon/` for reference and for
`python -m daemon.server`.

CI (`.github/workflows/rust-wheels.yml`) builds wheels for Linux x86_64/aarch64 and macOS arm64/x86_64 on every
push touching `rust/`, runs the end-to-end suite against the Rust daemon on Linux, attaches wheels to the release
on `v*` tags, and publishes to PyPI when a `PYPI_API_TOKEN` repository secret exists. Windows is not a target: the
daemon speaks over a Unix socket.
