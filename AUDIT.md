# Browser CLI — audit (2026-08-22)

Scope: the daemon + CLI as used by a coding agent for a real task (creating a Cloudflare Turnstile widget via the dashboard), plus a code read of `daemon/` and `cli/` and a controlled CPU measurement. Source at v0.2.1; the copy installed via pipx on this machine is **0.1.0** (see §7).

## 1. Summary

The design is right: a long-lived daemon owning one Chromium, isolated contexts per session, a Unix socket, and a thin CLI that any agent can call as a subprocess. The CLI itself is cheap (≈40 ms per call, no Playwright import on the daemon path). What hurts is everything *around* the browser:

| problem | measured impact | fix effort |
|---|---|---|
| Chromium runs headed at 1920×1080 with GPU compositing on | **181 % CPU** at idle on a dashboard page (GPU helper 173 %); observed **711 %** during the real task — the laptop heat | small |
| `snapshot` returns the first 100 of `body *` in document order | agent sees only the nav; main content is invisible → blind clicks, wrong button hit | small |
| `snapshot` selectors are non-unique (`button.group.flex`) | `click` hit the wrong "Create" — opened an unrelated panel | small |
| `navigate` waits for `networkidle` (10 s) | every SPA navigation costs 10 s and reports an error | trivial |
| no text/role-based targeting in the CLI | agent can't say "click the button labelled Create" | small |
| `capture` always full-page despite the `-f` flag and docs | flag is a no-op | trivial |
| `cleanup` does `pkill -f playwright` | kills *every* Playwright process on the machine, including other tools' | trivial |

Fixing the first two rows alone would have turned the Cloudflare task from 25 CLI calls with several mis-clicks and a cooked laptop into ~8 calls.

## 2. Resource usage (the heat)

### What was observed
During the task, `ps` showed the Chromium **GPU helper at 711 % CPU** and the renderer at 26 %, for a single tab sitting on the Cloudflare dashboard. Killing the daemon returned the machine to normal immediately.

### Controlled measurement
`scratch/cpu_probe.py` (included) launched Chromium four ways, loaded `https://dash.cloudflare.com/login`, and sampled total CPU of all "Chrome for Testing" processes (median of 6 samples over 15 s, page idle):

| config | total CPU | GPU helper |
|---|---:|---:|
| **A. current** — headed, 1920×1080, default GPU | **180.8 %** | 173.0 % |
| B. headed, 1280×800, `--disable-gpu` | 23.1 % | 11.4 % |
| C. B + `--force-prefers-reduced-motion` | 22.1 % | 10.6 % |
| D. headless (new), 1280×800 | 0.0 % | 0.0 % |

### Why
- Playwright's *Chrome for Testing* build does not get hardware-accelerated compositing on macOS the way installed Chrome does; with a headed window it falls back to a software/ANGLE path that burns CPU in the GPU process, scaled by window size and by page animation (the Cloudflare dashboard has continuous animated panels). 1920×1080 makes it worse.
- Nothing throttles the page when the agent isn't looking at it: no `--disable-renderer-backgrounding`, no pause between commands, no idle handling.

### Recommendations (in order of payoff)
1. **Launch flags**: add `--disable-gpu` and `--force-prefers-reduced-motion` (do *not* add `--disable-renderer-backgrounding`; we want background tabs throttled, which is the default). Measured: 181 % → 23 %.
2. **Default viewport 1280×800** (or accept `--viewport`). Fewer pixels to composite and screenshots are smaller; 1920×1080 is only needed to dodge mobile layouts, and 1280 already does that.
3. **Headless by default, headed on demand**: the user needs a visible window only to log in; afterwards the agent doesn't. Headless is a per-browser setting in Chromium, so keep **two lazily-launched browsers**: a headed one that exists only while some session is flagged `visible`, and a headless one for agent work. `browser <id> hide` / `show` move a session between them by handing over its storage state (`context.storage_state()` → `new_context(storage_state=…)`). Measured headless idle: ~0 %.
4. **Idle management**: after N minutes without commands, close the browser (keep the socket); store each session's `storage_state` JSON on disk and re-hydrate on the next command. This also makes sessions survive daemon restarts (today they die with it).
5. **Freeze idle pages**: via CDP, call `Page.setWebLifecycleState('frozen')` when a session has been idle for a few seconds and `'active'` right before the next command. Cheap, and it stops animation-heavy dashboards from spinning while the agent is thinking.
6. **Close contexts you don't need**: `create` makes a context + page; `list` calls `page.title()` on every session (a round-trip into each page) — fine at 1–2 sessions, not at 10.

## 3. Speed and reliability for agents

### 3.1 `snapshot` shows the wrong 100 elements
`daemon/browser.py` collects `document.body.querySelectorAll('*')` and slices to the first 100 in document order. On any real app the first 100 nodes are the header/sidebar wrappers, so the agent never sees the form or the primary button (this is exactly what happened: every `snapshot` showed only the Cloudflare sidebar until a CSS selector was guessed).

Fix: collect **interactive and landmark elements only**, in priority order, not "everything":
- `a[href], button, input, select, textarea, [role=button], [role=link], [role=tab], [role=menuitem], [role=option], [contenteditable]` plus headings `h1–h3` and `[role=dialog]`/`[role=alert]`.
- Skip `display:none`/zero-size elements (`getBoundingClientRect`, `checkVisibility()`), which also removes hidden cookie-consent trees (the Cloudflare snapshot returned 15 OneTrust inputs that aren't on screen).
- Raise the cap (500) and add `--all` for the old behaviour.
- Return `boundingBox` so an agent can also click by coordinate and reason about layout.
- De-duplicate the wrapper cascade: today `div#react-app`, `div.c_a`, `div.c_b`, … each repeat the same 200-char text.

### 3.2 Selectors aren't unique
`getSelector` returns `tag.class1.class2` — in utility-CSS apps (Tailwind, Cloudflare's dashboard) that matches dozens of elements. `browser <id> click button.group.flex` clicked the first match (the "Ask AI" button) instead of "Create" and opened an "enable API token for Agent Lee" panel. Two fixes:
- Make `ref` (`el_12`) **clickable**: the daemon keeps the last snapshot's element handles (`page.evaluate_handle` → `ElementHandle`) keyed by ref, and `click el_12` targets that exact node. This is how every mature agent browser tool works and removes the selector-guessing loop.
- When a CSS selector is emitted, verify uniqueness in the page (`querySelectorAll(sel).length === 1`) and otherwise fall back to `:nth-of-type` chains or a `text=` form.

### 3.3 Add text/role targeting
`click "Create"` should work. Playwright already has `get_by_role`, `get_by_text`, `get_by_label`, `get_by_placeholder`; expose them as `click --role button --name Create`, `type --label "Widget name" zera-web`. Cheaper for the agent than any snapshot round-trip, and robust across re-renders.

### 3.4 `navigate` waits for `networkidle`
`page.goto(domcontentloaded)` then `wait_for_load_state("networkidle", 10 s)`. SPAs with long-polling/analytics never go idle: every navigation to the dashboard returned `Timeout 10000ms exceeded` after 10 s even though the page was ready at ~1 s. Use `load` (or `domcontentloaded` + a short `wait_for_selector('body *:visible')`), make the wait configurable, and **never report a timeout as failure if the page has a URL and a title**.

### 3.5 Per-command overheads
- `click` follows with `wait_for_load_state("domcontentloaded")` — fine, but it should also settle briefly (`wait_for_timeout(100)`) so a snapshot immediately after sees the new state; today the agent adds `sleep` calls by hand.
- `type` uses `fill` — good (instant). For comboboxes that need key events (the hostname picker), add `--press-sequentially`.
- Every CLI call spawns Python (~40 ms) — acceptable. A `browser <id> batch` reading newline-delimited JSON from stdin would let an agent do "type, type, click, snapshot" in one process and one daemon round-trip; with the ref model this is where most of the latency win is.
- `screenshot` is JPEG q85 at 1920×1080 ≈ 200–300 KB; default to the viewport size and q70, add `--scale 0.5` for agents that only need layout.

### 3.6 Output size
The snapshot JSON for the Cloudflare page was ~40 KB for almost no useful information. With 3.1 applied it would be ~3 KB. Agents pay for every byte twice (reading, then reasoning).

## 4. Correctness bugs

| where | bug |
|---|---|
| `cli/main.py` `capture` | `full_page = True` by default and `-f` only sets it to `True`; the documented default ("viewport only") is never used. |
| `cli/main.py` `cleanup` | `pkill -f playwright` kills every process whose command line contains "playwright" — other tools' browsers, IDE extensions, and this daemon's socket server. Kill only children of this daemon (track PIDs) or only "Chrome for Testing" launched from `~/.cache/ms-playwright`. |
| `daemon/server.py` | `reader.read(10 MB)` is a single read; a request larger than one socket buffer is truncated. Use a length prefix or read until EOF (the CLI already calls `write_eof`). |
| `daemon/server.py` | signal handler calls `loop.create_task` from a non-loop thread context; works by luck on CPython. Use `loop.add_signal_handler`. |
| `daemon/session.py` | sessions are in-memory only; daemon restart or crash loses every login. Persist `storage_state` per session. |
| `daemon/browser.py` `console_logs` | reads `window.__browser_logs`, which nothing ever populates. Attach `page.on("console")` at session creation and buffer. |
| `daemon/browser.py` `screenshot` | `element.screenshot` on an element outside the viewport scrolls it; fine, but `query_selector` returns the *first* match (same uniqueness problem as click). |
| `cli/main.py` | `browser <id> delete` and `browser delete <id>` both exist; `list` prints a table while everything else prints JSON — agents have to special-case it. Always JSON (`--table` for humans). |
| anti-detection | UA pins `Chrome/123` while the runtime is Chromium 145; mismatched UA/Client-Hints is itself a bot signal. Derive the UA from `browser.version()`. |

## 5. Security notes

- The socket is created with default permissions in `~/.browser-daemon/`; any local process can drive a logged-in browser. `chmod 600` the socket (and the directory).
- `--no-sandbox` is unnecessary on macOS and weakens the renderer sandbox for whatever site the agent visits. Drop it outside Linux containers.
- Screenshots go to world-readable `/tmp` with predictable names (`browser_screenshot_<epoch>.jpg`); they frequently contain authenticated pages. Write to `~/.browser-daemon/shots/` with `0600`, or to a caller-supplied path only.
- There is no concept of *which agent* may use *which session*; fine for a single user, worth a note in the README.

## 6. What worked well

- The daemon/CLI split: `browser list` round-trips in ~40 ms; the agent never pays a Playwright start-up per command.
- `create` → user logs in → agent drives: exactly the right privacy boundary. The Cloudflare login completed in the user's hands; the agent never saw credentials.
- JSON everywhere (except `list`) made parsing trivial.
- `type` via `fill` and `press Enter` handled a React combobox correctly once the right element was known.

## 7. Packaging / drift

- `pipx list` reports **0.1.0** installed while `pyproject.toml` is **0.2.1**; the repo moved to `uv tool install`. The pipx copy should be removed (`pipx uninstall browser-automation-cli`) and reinstalled with uv to avoid two `browser` binaries drifting.
- `browser install` runs `python -m playwright install chromium` — downloads ~170 MB without asking; print the size and ask, or document it.
- No tests. The items above are all unit-testable against a local static page served by `python -m http.server` (snapshot contents, selector uniqueness, flag parsing) plus one Playwright smoke test.

## 8. Proposed order of work

1. Launch flags + 1280×800 default (`--disable-gpu`, reduced motion) — one-line change, 8× less CPU.
2. Snapshot rewrite: interactive/visible elements, bounding boxes, unique selectors, stable `ref`s usable by `click`/`type`.
3. `navigate` wait strategy; `click` settle; `capture -f` fix; `cleanup` scoped kill; JSON for `list`.
4. Headless-by-default with `show`/`hide` via storage-state hand-off; idle shutdown; persisted sessions.
5. Role/text/label targeting; `batch` command.
6. Socket permissions, screenshot location, drop `--no-sandbox` on macOS, UA derived from runtime.
7. Tests + reinstall via uv; bump to 0.3.0.

Items 1–3 are an afternoon and fix everything observed in the real task; 4–5 are what make it genuinely pleasant for agents.
