# Browser Automation CLI

> **If you are an LLM using this tool, read [SKILL.md](https://github.com/jshan9078/browser-automation-cli/blob/main/SKILL.md)**: or run `browser install skill` to add it to Claude Code / Codex / OpenCode. ([AGENTS.md](AGENTS.md) is for agents developing this repo.)

A lightweight, self-hosted browser automation tool with a background daemon and CLI client. Enables authenticated web automation, screenshots, compact page snapshots, and page interactions via simple CLI commands. Share the [`SKILL.md`](https://github.com/jshan9078/browser-automation-cli/blob/main/SKILL.md) file with your coding agent harness for seamless integration.

## Why This Exists

Coding agents need to interact with authenticated web apps. Existing solutions all have tradeoffs:

* **Chrome DevTools MCP**: requires Node.js, per-agent MCP server configuration, Google telemetry by default, and complex setup for each coding agent
* **BrowserMCP and similar tools**: require installing Chrome extensions, tie into specific ecosystems, and use MCP which bloats the agent's context window with tool definitions and protocol overhead
* **Playwright/Puppeteer scripts**: require writing code for every interaction, no persistent auth state
* **AI browser frameworks**: heavy, opinionated, and framework-locked

Browser CLI solves this with a persistent daemon that any agent can call via subprocess. No extensions, no MCP config, no SDKs, no ecosystem lock-in. Sessions persist across agent calls (and daemon restarts) so you only log in once.

## Benchmarks

On [BU Bench V1](https://github.com/browser-use/benchmark) (browser-use's 100-task benchmark, `opus-4-7`,
scored by their `gemini-2.5-flash` judge), Claude Code + browser-automation-cli tops every published
harness × browser-tool configuration:

![BU Bench V1 results](https://raw.githubusercontent.com/jshan9078/browser-automation-cli/main/docs/busbench-results.png)

Methodology and per-task scores: [`benchmarks/busbench/`](benchmarks/busbench/RESULTS.md).

## Install

```bash
uv tool install browser-automation-cli
browser install
```

If commands are not found after install, add `~/.local/bin` to your PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Which browser engine to use

**The managed engine (Chrome for Testing, the default once `browser install` has run) is the
recommended setup.** The alternative, `browser engine system`, launches your own installed
Chrome/Edge/Brave headless, and on macOS that collides with the app's identity: while the daemon
is running, LaunchServices thinks "Google Chrome is already running" and clicking the Chrome dock
icon fronts the invisible headless instance instead of opening a window. The managed build has its
own app identity, so your personal browser is never affected, its version is pinned instead of
auto-updating underneath long-running work, and headed login windows are visually distinct from
your own browsing.

```bash
browser install          # downloads the managed build; `engine auto` (default) then prefers it
browser engine managed   # or pin it explicitly
browser shutdown         # restart the daemon to apply an engine change
```

One caveat: Chrome for Testing identifies itself slightly differently than consumer Chrome, and
some aggressive bot-detection stacks treat it with more suspicion. If a site that worked before
starts throwing bot walls, try `browser engine system` (plus `browser shutdown` to restart) and
see if it clears: sessions, profiles, and logins are stored by the daemon, not the browser binary,
so they survive engine switches.

## Quick Start

### 1. Create a session (the daemon auto-starts)

```bash
browser create   # first command starts the daemon in the background (0.5.0+)
```

Nothing visible opens: the daemon runs Chromium headless. Manage it yourself with `browser daemon` (or the legacy `browser-daemon` alias) if you prefer; `BROWSER_NO_AUTOSTART=1` disables auto-start.

### 2. Log in when a site needs it

```bash
browser create --show     # opens a window so you can log in; `browser <id> hide` afterwards
```

A session is an isolated browser profile (cookies, storage). Log into any sites you need while the window is shown; the agent drives it hidden afterwards. Sessions survive daemon restarts.

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
browser install [--all]                    # download headless Chromium (Chrome for Testing, ~196 MB);
                                           # the headed build (~356 MB) downloads on first `show`, or now with --all
browser engine [auto|managed|system|<path>]  # managed (recommended) = pinned Chrome for Testing;
                                           # system = your installed Chrome/Edge/Brave (zero download,
                                           # but hijacks the app identity of your own browser while the
                                           # daemon runs); auto = managed if downloaded, else system
browser profile [status]                   # by DEFAULT sessions use a persistent "default" profile:
                                           # the first session opens a window to sign in, every later
                                           # session reuses that login. Manage it with:
browser profile <name> | new <name>        #   switch to / create a named persistent profile
browser profile delete <name>              #   delete a profile + its logins (each is a full Chrome
                                           #   profile, ~100 MB+; delete ones you no longer need)
browser profile ephemeral                  #   make throwaway the default for new sessions
browser create --profile <name>            #   per-session: this session uses its own persistent login
browser create --ephemeral                 #   per-session: throwaway, isolated
browser <id> show | hide                   #   flip a profile visible<->headless seamlessly (sessions kept)
                                           #   (different --profile = concurrent & isolated; same = shared tabs)
browser cleanup                            # kill Chromium processes launched from Playwright's cache
browser install skill                      # install the agent skill into Claude Code / Codex / OpenCode
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
| `click <target> [--double]` | Also `click --at X,Y` to click raw viewport pixels (canvas / vision, no DOM target; screenshot first, pixels map 1:1) |
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

**Targets:** `@e12` (ref from snapshot, preferred) · CSS selector · `text=Create` · `role=button[name=Create]` · `label=Email` · `placeholder=Search` · or flags `--text / --role [--name] / --label / --placeholder`. Ambiguous CSS selectors are refused (strict mode) instead of clicking the first match. For canvas / vision cases with no DOM target, `click --at X,Y` clicks raw viewport pixels (take a `screenshot` first; its pixels map 1:1 to click coordinates).

***

## Architecture

* **Daemon** (`browser-daemon`): Unix socket server (`~/.browser-daemon/socket`, mode 600) owning a headless Chromium, plus a headed one that exists only while some session is `show`n.
* **CLI** (`browser`): a native Rust binary driving Chrome over raw CDP, ~2 ms per call, no Python/Node at runtime.
* **Sessions**: one isolated browser context each. Hidden sessions are **frozen** after 10 s idle (script execution paused, ~3% CPU on animated dashboards; callbacks that fire while frozen are dropped, so `BROWSER_FREEZE_AFTER=0` disables it) and **hibernated** to `~/.browser-daemon/sessions/<id>.json` (cookies + storage + URL) after 10 min idle or on shutdown; they are rehydrated transparently on the next command. Tune with `BROWSER_FREEZE_AFTER` / `BROWSER_HIBERNATE_AFTER` (seconds).
* **Resource profile** (M4, Cloudflare dashboard parked in a session): 2% CPU / 1.1 GB vs 264% CPU / 2.1 GB for v0.2. See [`benchmarks/`](benchmarks/) for methodology and measurements.

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

Run `browser install skill` to install [`SKILL.md`](SKILL.md) into Claude Code / Codex / OpenCode, or share the file with any other harness.

## Implementation

Written entirely in Rust, one binary (`browser`, with a `daemon` subcommand) plus a `browser-daemon`
compat shim, driving Chrome over raw CDP via a websocket. No Python, Playwright, or Node at runtime:
`browser install` downloads the Chrome-for-Testing build directly, and `capture` is native too. ~2 ms
per call, daemon RSS −90 MB vs the old Python build, frame- and shadow-DOM-aware snapshots. See the
[`benchmarks/`](benchmarks/) directory for measurements. Since 0.4.0 the PyPI package ships these binaries under the same name
(wheels for Linux x86_64/aarch64, macOS arm64/x86_64).

```bash
cargo build --release
./target/release/browser list          # the daemon auto-starts (`browser daemon` runs it in the foreground)
```

## Development

```bash
cargo build --release
BROWSER_CLI=$PWD/target/release/browser BROWSER_DAEMON=$PWD/target/release/browser-daemon \
  python3 -m unittest -v tests/test_cli.py                        # end-to-end tests (needs python3 + a Chromium)
python3 benchmarks/performance-test/run.py <label>               # benchmark (latency, tokens, idle CPU/RSS)
python3 benchmarks/performance-test/compare.py baseline <label>
```

## Troubleshooting

| Symptom | Fix |
| :-- | :-- |
| `Command not found: browser` | `export PATH="$HOME/.local/bin:$PATH"` |
| `Daemon not running` | Auto-start was disabled or failed, `browser daemon &`, check `~/.browser-daemon/daemon.log` |
| Browser doesn't launch | `browser install` |
| `Session not found` | `browser list` |
| `ref @eN is unknown or stale` | Page changed; run `snapshot` again |
| `strict mode violation` | Selector matched several elements; use an `@ref`, `--text`, or a tighter selector |
| Stale Chromium processes | `browser cleanup` |

### Installing the binaries

```bash
curl -fsSL https://raw.githubusercontent.com/jshan9078/browser-automation-cli/main/install.sh | sh
```

or simply `uv tool install browser-automation-cli` (the PyPI wheels are the Rust binaries). The script installs
`browser` and `browser-daemon` into `~/.local/bin` (set `BROWSER_CLI_BIN` to change); to build from source: `cargo build --release`.

Wheel: `uvx maturin build --release` → `uv tool install target/wheels/browser_automation_cli-*.whl`.

CI (`.github/workflows/rust-wheels.yml`) builds wheels for Linux x86_64/aarch64 and macOS arm64/x86_64 on every
push touching the Rust sources, runs the end-to-end suite against the Rust daemon on Linux, attaches wheels to the release
on `v*` tags, and publishes to PyPI when a `PYPI_API_TOKEN` repository secret exists. Windows is not a target: the
daemon speaks over a Unix socket.
