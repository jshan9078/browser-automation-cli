# Browser CLI — performance & efficiency work (v0.2.1 → v0.3.0)

Follow-up to [AUDIT.md](AUDIT.md). Every change below was measured before and after with the
same harness (`scratch/bench/`), on an Apple M4 / 24 GB, Playwright 1.58, Chromium 1234,
2026-08-22. Raw results: `scratch/bench/results/*.json`.

## 1. Headline numbers

Agent-style task on the local test app (create → navigate SPA → snapshot → fill form → click →
verify → navigate → back → screenshot), medians of 3 runs, driven through the real `browser` CLI:

| | v0.2.1 | v0.3.0 | |
|---|---:|---:|---|
| whole task, wall-clock (old API only) | 12.1 s | 1.0 s | 12× — `networkidle` wait removed |
| whole task, wall-clock (incl. new-API steps) | 31.9 s¹ | 1.7 s | |
| tokens returned to the agent per task | 6,687 | 2,018 | 3.3× |
| `snapshot` tokens (test app) | 6,201 | 721 | 8.6×, and the target button is now *in* it |
| `snapshot` tokens, Cloudflare login | 6,696 | 245 | 27× |
| `snapshot` tokens, GitHub login | 5,751 | 222 | 26× |
| screenshot size | 95 KB | 54 KB | |
| ambiguous CSS selector (`button.group.flex`) | clicks wrong button | refused with error | |
| Cloudflare dashboard parked in a session, CPU | **264 %** | **2.0 %** (94 % in the first 10 s) | |
| same, RSS of the daemon's process tree | 2.1 GB | 1.1 GB | |
| test app parked, CPU / RSS | 10.6 % / 1.25 GB | 8 % / 0.48 GB | |
| CLI call overhead (`list`) | 51 ms | 40 ms | Python start-up floor is 25 ms |

¹ v0.2.1 spends 10 s timing out on each of the two new-API steps it cannot do (`click --text`, `navigate -s`).

### Headed mode (`create --show`, used for manual login)

Measured separately (`scratch/bench/headed_probe.py`) because visible sessions are deliberately never
frozen: per-command latency is identical to headless; a shown window parked on the Cloudflare
dashboard costs **27 % CPU (GPU helper 11 %), 1.6 GB** vs 301 % / 2.1 GB in v0.2.1 — the launch-flag
and viewport effect. `hide` carries cookies + localStorage into the headless browser (verified) and the
session then freezes at 8 % / 0.45 GB; `show` brings the same state back. `storage_state()` does not
capture sessionStorage or IndexedDB, so the rare site that keeps its auth only there needs a re-login
after `hide`; finish multi-step logins before hiding, since the hand-off re-navigates to the current URL.

## 2. Method

- **Harness** — `scratch/bench/run.py <label>` starts the local test site and a daemon from the
  working tree, runs the scripted task through `python -m cli.main`, records per-command latency,
  bytes/approx tokens (`chars/4`), correctness checks (did the snapshot expose the deep "Create"
  button; which button did the ambiguous selector hit; did the form flow complete), then parks a
  session on a page and samples CPU/RSS. `compare.py a b c` prints the table.
- **Test site** — `scratch/bench/site/dashboard.html` mimics the failure modes from the audit:
  ~250 nav wrapper nodes before the main content, the form and "Create" button deep in the DOM,
  two `button.group.flex` (the ambiguous selector), a hidden consent tree with 10 inputs, a CSS
  spinner, and a `/poll` long-poll so the page never reaches `networkidle`.
- **CPU** — summed CPU-time deltas (`ps -o time`, 10 ms resolution) over the daemon's whole
  process tree across a 5 s window. macOS `ps pcpu` is a decaying lifetime average and under-reports
  by 10×; `top` truncates command names so the daemon's Chromium cannot be told from the user's
  Chrome. Both were tried and discarded.
- **Real site** — `BENCH_IDLE_URL=https://dash.cloudflare.com/login` re-runs the idle measurement on
  the animation-heavy page from the audit (the daemon's desktop UA makes Cloudflare serve the full
  animated dashboard; with Playwright's default `HeadlessChrome` UA it idles at 5 %, which is why an
  early probe looked fine).

## 3. Changes, in the order they were measured

| # | change | measured effect | file |
|---|---|---|---|
| 1 | `navigate` waits for `load` instead of `networkidle`; `networkidle` optional and never fatal (`settled: false`) | SPA navigate 10.13 s → 0.11 s and reports success; static 0.61 → 0.09 s | `daemon/browser.py` |
| 2 | Launch flags `--disable-gpu --force-prefers-reduced-motion --disable-background-networking …`; drop `--no-sandbox` off Linux; viewport 1920×1080 → 1280×800 | Cloudflare idle 301 % → 100 % (GPU helper 219 % → 15 %); screenshots 95 → 62 KB; **test app 10 → 18 %** (CSS spinner now software-rastered — the one regression, removed by #3) | `daemon/server.py`, `daemon/session.py` |
| 3 | Headless by default; headed browser launched lazily only while a session is `show`n; `show`/`hide` hand the session over via `storage_state` | RSS 1.0 GB → 0.47 GB (test app), 1.7 → 1.1 GB (Cloudflare); GPU process gone; per-command latency −30 % | `daemon/server.py`, `daemon/session.py` |
| 4 | Freeze hidden sessions after 10 s idle (`Emulation.setScriptExecutionDisabled`), thaw on next command; hibernate to disk after 10 min / on shutdown; rehydrate on demand (sessions now survive restarts) | Cloudflare parked: 83–94 % → **2 %**; thaw adds no measurable latency | `daemon/session.py` |
| 5 | Snapshot rewrite: visible interactive elements + h1–h3/live regions only, flat one-line format, stable `@eN` refs, `[below]/[above]`, select options, states; `--all`, `--json` (boxes + verified-unique selectors), scope selector, `--max` | 6,201 → 721 tokens on the test app, 27× on Cloudflare; hidden consent inputs gone; target always present | `daemon/browser.py` |
| 6 | Targeting: `@ref`, `--text`, `--role/--name`, `--label`, `--placeholder`, `text=`/`role=` prefixes; CSS goes through Playwright strict mode | ambiguous selector: wrong click → refused; `click --text Create` 0.16 s | `daemon/browser.py`, `cli/main.py` |
| 7 | Post-action settle: wait for DOM quiet 60 ms (max 500 ms) after click/press/navigate | click 0.07 → 0.14 s; a snapshot immediately after an action now reflects it (no hand-written sleeps). Tuned down from 100 ms quiet/25 ms tick, which had made it 0.20 s | `daemon/browser.py` |
| 8 | `-s/--snapshot` on any action; `batch` (JSON lines, one round-trip, stop at first failure); `text`, `wait`, `scroll`, `eval`, `console` | navigate+snapshot in one call 0.13 s; 4 ops in one batch 0.15 s vs ~0.5 s as 4 calls | both |
| 9 | Screenshot JPEG q70 at viewport, saved 0600 under `~/.browser-daemon/shots/`; socket + state dir 0700/0600; `cleanup` kills only Playwright-cache Chromium; `list` is JSON; UA derived from runtime version; console buffered via `page.on("console")`; read-until-EOF socket protocol; `loop.add_signal_handler`; only unlink a socket we own | 54 KB screenshots; correctness items from AUDIT §4–5 closed | both |

### Bugs found by the measurements (not in the audit)

- **Freezing a busy session** deadlocked it: the housekeeper counted a command *in flight* (e.g. a
  10 s locator wait) as idle and froze the page underneath it. Sessions now carry a `busy` counter.
- **Persisting a frozen page hung shutdown**: `storage_state()` cannot run on a page with scripts
  disabled; `_detach` thaws first.
- **Old daemon unlinking the new daemon's socket** during graceful shutdown — inode check added.

## 4. Things tried and rejected (with numbers)

| approach | result | why rejected |
|---|---|---|
| `Page.setWebLifecycleState: frozen`, `Emulation.setIdleOverride`, backgrounding the tab (even with Playwright's `--disable-background-timer-throttling`/`--disable-renderer-backgrounding` removed) | 95 % → 95 % | no effect: headless pages are never "hidden", and Playwright disables the throttling these depend on |
| `Emulation.setCPUThrottlingRate: 50` | 95 % → **144 %** | throttling busy-waits |
| `Debugger.pause` / `resume` | 95 % → 4 % on Cloudflare — but on a quiet page the pause only arms at the *next* JS statement; `resume` then fails ("not paused") and the next action trips the armed pause and hangs forever | unreliable thaw (found by the test suite) |
| `Emulation.setVirtualTimePolicy: pause` | 95 % → 2.5 %, thaws cleanly | freezes `Date.now()` (token-expiry logic drifts) and replays every missed timer on resume (266 % burst) |
| **`Emulation.setScriptExecutionDisabled`** (chosen) | 89 % → 2.5–3.3 %, thaws cleanly, +0 ms | timer/fetch/rAF callbacks that fire *while* frozen are dropped (verified with a probe) — hence the 10 s idle threshold, hidden-only, and `BROWSER_FREEZE_AFTER=0` to disable |

## 5. What the state of the art does (research summary)

Sources and details in the research notes; the patterns that matter for this tool:

- **Text snapshot with opaque short refs, interactive-only, flat** — Playwright MCP (`- button "Save" [ref=e9] [cursor=pointer]`), Vercel agent-browser (`@e2 [button] "Submit"`, ~200–400 tokens per page), browser-use (`[12]<button>Submit</button>`), Chrome DevTools MCP (`uid`), BrowserGym (`bid`). Refs are cached on the DOM node and resolved server-side, so the agent never guesses selectors. v0.3 follows agent-browser's flat format (the most token-dense of the group) and Playwright MCP's ref semantics (stable until navigation, stale-ref error forces re-snapshot).
- **Return the new state with the action** — Playwright MCP does this by default (`--snapshot-mode`), Chrome DevTools MCP opt-in (`includeSnapshot`). v0.3: `-s` opt-in, to keep default responses at ~25 tokens.
- **Settle, don't sleep** — Playwright MCP waits 500 ms for triggered work after every action; browser-use batches up to 4 actions per step. v0.3: DOM-quiet settle (60 ms quiet, ≤500 ms) + `batch`.
- **Viewport** — Anthropic computer-use recommends 1280×800 for web apps (≈1–1.8k tokens per screenshot), OpenAI CUA 1024×768 default; nobody runs 1920×1080.
- **Headless + persistent daemon** — agent-browser (Rust daemon, auto-exit after idle), Playwright MCP `--storage-state`/`--save-session`, Stagehand action caching. v0.3: headless default, lazy headed browser, freeze/hibernate/rehydrate.
- **Benchmarks** — WebVoyager (saturated, ~98 %), Online-Mind2Web (human-judged; Operator 61 %, Browser Use 30 %), WebArena, OSWorld. Standard metrics: success rate, steps per task (agent ÷ human), tokens or $ per task. The harness here reports the same three for one task; §6 proposes growing it.

## 6. Proposed next steps (not done)

Ordered by expected payoff; each should be measured with the same harness.

1. **Real-task benchmark set.** Five scripted tasks on live sites (GitHub issue search, HN front page extraction, a Cloudflare dashboard flow in a `show`n session, a localhost React form, Wikipedia navigation), each run by an actual LLM agent with the CLI as its only tool, recording success, CLI calls per task, and tokens in/out. This is the number that matters; the current harness measures the tool, not the agent.
2. **Link-dense pages.** HN (3.5k tokens) and Wikipedia (4.3k) are now the worst case because every link is listed. Add `--viewport` (browser-use's default: only elements within the viewport ± 1000 px) and `--no-href`, and measure agent success with/without.
3. **Frames and shadow DOM.** The snapshot only walks the light DOM of the top frame. Playwright MCP and browser-use pierce both. Many OAuth and payment widgets are iframes.
4. **`find <text>`** — grep the snapshot server-side and return only matching lines (Playwright MCP `browser_find`); cheaper than scoping by selector when the agent knows what it wants.
5. **Screenshot `--scale 0.5`** for layout-only checks; expose `--annotate` (overlay `@eN` labels) for vision-capable agents, as agent-browser does.
6. **Drop Python start-up (25 ms of the 40 ms per call)** — a tiny C/Rust or shell client, or `batch` as the documented fast path. Only worth it once the agent-level benchmark shows call count dominating.
7. **Linux/Windows pass** — the `--no-sandbox` and `chrome-headless-shell` assumptions were only measured on macOS.
8. **CI** — run `tests/test_cli.py` (20 tests, ~25 s) on push.

## 7. Rust rewrite (v0.4.0-alpha) — measured against the same harness

`rust/` contains a Rust client (`browser`) and daemon (`browser-daemon`) speaking the identical socket
protocol, driving Chromium over raw CDP (no Playwright, no Node). The injected JS moved over
unchanged except that the snapshot now walks same-origin iframes and open shadow roots, and targets
resolve through the same role/name code the snapshot uses (strict mode, actionability retries,
"covered by <div#banner>" errors). Validated by the same 20 end-to-end tests (`BROWSER_CLI=… BROWSER_DAEMON=…`).

| | Python v0.3.0 | Rust | |
|---|---:|---:|---|
| CLI call overhead (`list`) | 40 ms | **2 ms** | no interpreter start-up |
| `snapshot` | 51 ms | **6 ms** | |
| `type` | 52 ms | 6 ms | |
| `click` (incl. 60 ms DOM-settle) | 145 ms | 83 ms | |
| whole benchmark task | 1.7 s | **1.0 s** | |
| daemon RSS, test app | 478 MB | **387 MB** | Node driver (~150 MB) gone |
| daemon RSS, Cloudflare | 1122 MB | 1028 MB | |
| Cloudflare parked CPU | 2 % | 4 % | same freeze mechanism |
| headed window parked on Cloudflare | 27 % | 4 % | |
| binaries | Python + Playwright + Node driver | 0.5 MB + 1.0 MB | Chromium still ~170 MB |
| daemon start-up | 0.73 s | 0.41 s | |

Agent benchmark, all 17 tasks × 2 attempts (pass@2, same Sonnet subagents, see AGENTBENCH.md): pass@1 17/17 and pass@2 17/17 on both; over both attempts Rust used 483 CLI calls vs 958 and 14 failed calls vs 72. Attempt 1 alone: Totals over 17 tasks — calls 693 → 231, failed calls 62 → 8, tool-output tokens 32,929 → 23,761; 17/17 pass on both. Iframe ticket
438 → 9 calls (331 s → 12 s), shadow-DOM flags 18 → 8. One thing got worse and is logged honestly: `press`/`type --sequential` synthesize key events from
a small key table rather than Playwright's full keyboard layout. (A click blocked by an overlay
initially waited the full 10 s timeout; it now fails after 1 s if the *same* covering element is still
there — measured 1.03 s — while missing/hidden targets keep waiting for the page to catch up.)

Known gaps vs the Python daemon: `capture`/`install` still delegate to the Python package; no
`--sequential` IME text; sessionStorage/IndexedDB not persisted (same as before); only same-origin
frames are visible (cross-origin frames need `Target.setAutoAttach`, not done).

## 8. Reproduce

```bash
uv sync
.venv/bin/python -m unittest -v tests/test_cli.py
.venv/bin/python scratch/bench/run.py mychange 3
BENCH_IDLE_URL=https://dash.cloudflare.com/login .venv/bin/python scratch/bench/run.py mychange_cf 2
.venv/bin/python scratch/bench/compare.py baseline final mychange
.venv/bin/python scratch/bench/real_pages.py mychange        # snapshot size on real pages
```

`git stash` the working tree and run `run.py baseline` to regenerate the v0.2.1 numbers.

Rust: `cd rust && cargo build --release`, then prefix any of the above with
`BROWSER_CLI=$PWD/rust/target/release/browser BROWSER_DAEMON=$PWD/rust/target/release/browser-daemon`.
