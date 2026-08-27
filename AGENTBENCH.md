# Benchmarks

Everything measured while taking browser-automation-cli from v0.2.1 to the Rust-based v0.4.x, in two
layers: a **tool benchmark** (the daemon and CLI in isolation) and an **agent benchmark** (fresh LLM
agents completing verifier-judged tasks with only the `browser` CLI). All numbers below were
produced by the scripts in `benchmarks/performance-test/` and `benchmarks/development-bench/`; raw results live next to them.
Hardware: Apple M4, 24 GB. Dates: 2026-08-22/23.

## 1. Agent benchmark

### Method
- **Environment** — a deterministic local admin app (`benchmarks/development-bench/app/`): login gate, searchable
  paginated table, two-step wizard with autocomplete, settings form, confirm modal, inline rename, plus a
  *hard tier* where each page forces a different strategy (table below). The server keeps state in memory
  and exposes `/__state` and `/__reset` to the harness only; one live-site task (Wikipedia) is included.
- **Verifiers** — every task is judged from **application state** (or, for extraction tasks, an `ANSWER:`
  line against ground truth), never from what the agent says it did.
- **Agents** — one fresh subagent per task, given only the rules, a session id and the task text; no repo
  docs beyond `browser --help`, no memory between tasks, and the orchestrator never sees their transcripts.
- **Metrics** — success; CLI calls and failed calls counted from the daemon's own request log; wall-clock
  first→last call; tool-output tokens (bytes the agent read ÷ 4); agent tokens (the subagent's total
  context); daemon CPU-seconds and RSS over the task.
- **pass@k** — every task was attempted twice per implementation; pass@1 = all attempts passed, pass@2 =
  at least one passed.
- Run it: `harness.py setup <task>` → give the printed prompt to a fresh agent → `harness.py verify …` →
  `harness.py passk`.

| hard-tier task | what it forces |
|---|---|
| h1 canvas chart | **screenshot** — the data exists only as pixels |
| h2 form inside a same-origin iframe | frame-aware snapshot/targeting |
| h3 toggle inside shadow DOM | shadow-root-aware snapshot |
| h4 audit log: 3 s delayed load, "Load more" pagination, target on page 3 | waiting + multi-page search |
| h5 announcement banner overlays the Save button after 1.5 s | intercepted click → dismiss |
| h6 infinite-scroll list, target ~4 loads down | scrolling strategy |
| h7 drag-and-drop reorder, keyboard alternative only in an aria hint | reading a11y hints |
| h8 calendar date picker, no typing | multi-click navigation |
| h9 export behind a password re-confirmation modal, then a one-time code | multi-step dialog + extraction |
| h10 display-name validation (max 20 chars) | noticing an error and recovering |

### Results — pass@2, 17 tasks, two attempts each

| implementation · model | runs | pass@1 | pass@2 | CLI calls | failed calls | wall total | median calls / task | median wall / task | tool-output tokens | agent tokens | median daemon CPU-s | median RSS |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Python 0.3.0 · Sonnet | 35 | 17/17 | 17/17 | 958 | 72 | 29 min | 16 | 34 s | 80,393 | 1.71M | 0.79 | 452 MB |
| Rust 0.4.0 · Sonnet | 34 | 17/17 | 17/17 | 483 | 14 | 18 min | 12 | 28 s | 50,048 | 1.55M | 0.46 | 375 MB |
| Rust 0.4.0 (PyPI) · Haiku | 34 | 16/17 | 17/17 | 499 | 20 | 32 min | 13 | 50 s | 69,727 | 1.26M | 0.64 | 372 MB |

v0.2.1 (the version before this work) cannot run the suite at all: its snapshot returned the first 100
DOM nodes (the form was never visible) and ambiguous CSS clicks hit the wrong button, so there is no
agent-level row for it — see the tool benchmark below for how it compared.

### Per task — attempt 1 · attempt 2 (✅/❌ calls / wall / failed calls)

| task | Python 0.3.0 · Sonnet | Rust 0.4.0 · Sonnet | Rust 0.4.0 (PyPI) · Haiku |
|---|---|---|---|
| t1 create project (2-step wizard, autocomplete) | ✅ 19c/46s/4f · ✅ 20c/58s/0f | ✅ 16c/47s/0f · ✅ 17c/45s/0f | ✅ 22c/86s/0f · ✅ 13c/52s/1f |
| t2 archive (page 2 + confirm modal) | ✅ 20c/36s/5f · ✅ 11c/31s/0f | ✅ 15c/29s/0f · ✅ 10c/26s/0f | ✅ 8c/24s/0f · ✅ 11c/44s/0f |
| t3 settings (checkbox + select) | ✅ 11c/28s/0f · ✅ 11c/24s/0f | ✅ 10c/22s/0f · ✅ 9c/20s/0f | ✅ 10c/37s/0f · ✅ 9c/32s/0f |
| t4 inline rename | ✅ 12c/20s/2f · ✅ 14c/33s/0f | ✅ 9c/20s/0f · ✅ 7c/15s/0f | ✅ 16c/59s/0f · ✅ 11c/41s/0f |
| t5 count archived over 4 pages | ✅ 17c/35s/0f · ✅ 16c/39s/0f | ✅ 17c/60s/3f · ✅ 17c/32s/0f | ✅ 12c/45s/0f · ✅ 14c/53s/0f |
| t6 extract account email | ✅ 9c/16s/0f · ✅ 7c/12s/0f | ✅ 8c/35s/0f · ✅ 8c/16s/1f | ✅ 8c/24s/0f · ✅ 8c/23s/0f |
| t7 live Wikipedia infobox | ✅ 3c/8s/1f · ✅ 3c/7s/0f | ✅ 2c/4s/0f · ✅ 2c/4s/0f | ✅ 3c/8s/0f · ✅ 4c/15s/0f |
| h1 canvas chart (screenshot-only data) | ✅ 16c/28s/5f · ✅ 8c/23s/0f | ✅ 9c/26s/0f · ✅ 11c/21s/0f · ✅ 30c/126s/0f | ✅ 11c/39s/1f · ✅ 37c/130s/3f |
| h2 form inside an iframe | ✅ 438c/331s/21f · ✅ 27c/237s/4f | ✅ 9c/12s/0f · ✅ 10c/13s/0f | ✅ 11c/44s/0f · ✅ 12c/54s/1f |
| h3 toggle inside shadow DOM | ✅ 18c/63s/1f · ✅ 18c/66s/1f | ✅ 8c/19s/0f · ✅ 8c/12s/0f | ✅ 10c/39s/0f · ✅ 5c/23s/0f |
| h4 delayed load + "Load more" pagination | ✅ 20c/41s/5f · ✅ 20c/59s/2f | ✅ 13c/35s/0f · ✅ 23c/199s/2f | ✅ 21c/91s/0f · ✅ 14c/48s/0f |
| h5 banner overlaying the Save button | ✅ 11c/24s/0f · ✅ 22c/54s/6f · ✅ 16c/51s/1f | ✅ 12c/46s/2f · ✅ 12c/27s/2f | ✅ 16c/55s/1f · ✅ 19c/72s/2f |
| h6 infinite scroll list | ✅ 26c/28s/2f · ✅ 21c/27s/0f | ✅ 47c/23s/0f · ✅ 68c/35s/0f | ✅ 19c/71s/0f · ✅ 50c/266s/5f |
| h7 reorder (drag-and-drop, keyboard hint) | ✅ 15c/34s/2f · ✅ 13c/36s/1f | ✅ 14c/33s/2f · ✅ 13c/36s/1f | ✅ 8c/30s/0f · ✅ 14c/68s/1f |
| h8 calendar date picker | ✅ 13c/33s/2f · ✅ 19c/53s/1f | ✅ 18c/33s/1f · ✅ 14c/30s/0f | ✅ 16c/56s/2f · ✅ 21c/78s/1f |
| h9 password re-confirm + one-time code | ✅ 17c/32s/4f · ✅ 13c/28s/0f | ✅ 13c/32s/0f · ✅ 11c/32s/0f | ✅ 13c/43s/1f · ✅ 16c/55s/0f |
| h10 validation error recovery | ✅ 17c/63s/2f · ✅ 17c/63s/0f | ✅ 11c/26s/0f · ✅ 12c/44s/0f | ❌ 19c/81s/0f · ✅ 18c/60s/1f |

Notes:
- **Python vs Rust (same model):** identical pass rates; Rust does the work with roughly half the calls
  and a fifth of the failed calls. The iframe task is the sharpest case: Python needed 438 calls
  (typing into the frame one keypress at a time) and, on attempt 2, 27 calls by navigating to the frame URL
  directly; Rust's frame-aware snapshot makes it a 9–12 call task.
- **Haiku on the published 0.4.0:** same call counts as Sonnet (median 13 vs 12), slower wall time (more
  thinking per step), 26 % fewer agent tokens. Its single miss (h10, attempt 1) was interpretation, not
  tooling: the app rejected the 27-char name and Haiku saved the word-boundary prefix "Acme Ops Platform"
  instead of the literal 20-char prefix the task asks for; attempt 2 passed.
- Variance is real on every row (e.g. h6 on Haiku: 19 then 50 calls; h4 on Rust/Sonnet: 35 s then 199 s
  from the agent's own long `wait`s), which is why two attempts is the floor for judging a change.
- Python h5 has three attempts: the first predates a fix to the scenario itself (the banner didn't cover
  the button).

### Other recorded runs

| run | task | result | calls | failed | wall | note |
|---|---|---|---:|---:|---:|---|
| fable | t1 create project (2-step wizard, autocomplete) | ✅ | 19 | 2 | 68 s | orchestrator model (Fable), before standardising on Sonnet |
| fable | t2 archive (page 2 + confirm modal) | ✅ | 10 | 2 | 67 s | orchestrator model (Fable), before standardising on Sonnet |
| fable | t3 settings (checkbox + select) | ✅ | 12 | 2 | 61 s | orchestrator model (Fable), before standardising on Sonnet |
| rust-headed | h1 canvas chart (screenshot-only data) | ✅ | 30 | 0 | 126 s | visible window (`BENCH_VISIBLE=1`); typed text was dropped in a non-frontmost window → fixed with focus emulation |

A first Rust h1 run (46 calls) is kept as `h1_canvas_chart.rust-contaminated.json` and excluded above:
the agent found the stale globally installed 0.2.1 client, whose `type` payload the new daemon misread.
The daemon now accepts the legacy payload and calls are counted daemon-side.

## 2. Tool benchmark (daemon + CLI, no LLM)

`benchmarks/performance-test/run.py` drives a scripted task (create → navigate SPA → snapshot → fill form → click →
verify → navigate → back → screenshot) through the real CLI against a local test app that reproduces the
original failure modes (deep nav DOM, hidden consent tree, ambiguous `button.group.flex`, long-poll that
never reaches `networkidle`), then parks a session on a page and samples CPU/RSS. Idle CPU uses
`ps -o time` deltas over the daemon's process tree (macOS `ps pcpu` is a lifetime average and misleads).

### v0.2.1 → v0.3.0 (Python) → v0.4.0 (Rust)

| | v0.2.1 | v0.3.0 Python | v0.4.0 Rust |
|---|---:|---:|---:|
| CLI call overhead (`list`) | 51 ms | 40 ms | **2 ms** |
| `navigate` to an SPA with long-polling | 10.1 s (reported as error) | 0.13 s | 0.11 s |
| `snapshot` | 78 ms | 51 ms | **6 ms** |
| `type` / `click` | 56 / 80 ms | 52 / 145 ms¹ | 6 / 83 ms¹ |
| whole scripted task | 12.1 s | 1.7 s | **1.0 s** |
| tokens returned per task | 6,687 | 2,018 | 1,969 |
| `snapshot` tokens, test app | 6,201 (target button missing) | 721 | 721 |
| `snapshot` tokens, Cloudflare login / GitHub login | 6,696 / 5,751 | 245 / 222 | 245 / 222 |
| ambiguous CSS selector | clicks the wrong button | refused (strict) | refused (strict) |
| screenshot | 95 KB | 54 KB | 54 KB |
| daemon RSS, test app parked | 1.25 GB | 478 MB | **387 MB** |
| Cloudflare dashboard parked, CPU / RSS | **264 % / 2.1 GB** | 2 % / 1.1 GB | 4 % / 1.0 GB |
| headed window parked on Cloudflare, CPU | 301 % | 27 % | 4 % |
| daemon start-up | 0.84 s | 0.73 s | 0.41 s |
| runtime dependencies | Python + Playwright + Node driver | same | none (Chromium only) |

¹ includes the deliberate 60 ms DOM-settle after actions so the next snapshot reflects the result.

### What each change bought (measured one at a time, v0.2.1 → v0.3.0)

| change | effect |
|---|---|
| `navigate` waits for `load`, `networkidle` optional and never fatal | SPA navigate 10.1 s → 0.11 s |
| `--disable-gpu`, reduced motion, 1280×800 viewport, no `--no-sandbox` off Linux | Cloudflare idle 301 % → 100 % CPU; screenshots 95 → 62 KB |
| headless by default, headed browser only while a session is `show`n | RSS 1.0 → 0.47 GB; GPU process gone |
| freeze idle hidden sessions (`setScriptExecutionDisabled`), hibernate to disk after 10 min | Cloudflare parked 83–94 % → 2 % CPU; sessions survive restarts |
| snapshot rewrite: visible interactive elements, flat `@eN` refs | 6,201 → 721 tokens; 27× on real login pages; target always present |
| ref / text / role / label targeting, strict mode | wrong click → refused |
| 60 ms DOM-settle after actions; `-s` inline snapshot; `batch` | no hand-written sleeps; 4 ops in one round-trip 0.15 s |

Freeze mechanisms tried and rejected, with numbers: `Page.setWebLifecycleState` / idle override /
background throttling (no effect — headless pages are never hidden), CPU throttling (95 % → 144 %,
busy-waits), `Debugger.pause` (only arms at the next JS statement; quiet pages hang on resume), virtual
time (freezes `Date.now`, replays timers in a 266 % burst). `setScriptExecutionDisabled` drops callbacks
that fire while frozen, hence the 10 s idle threshold, hidden-only, `BROWSER_FREEZE_AFTER=0` to disable.

### Rust specifics
Raw CDP over a websocket (no Playwright, no Node); the injected JS walks same-origin iframes and open
shadow roots, and targets resolve through the same role/name code the snapshot uses (strict mode,
actionability retries, "covered by `<div#banner>`" after 1 s of the same blocker). Validated by the same
20 end-to-end tests (`BROWSER_CLI=… BROWSER_DAEMON=…`), on macOS and on Linux in CI. Known gaps: no IME
text for `--sequential`, sessionStorage/IndexedDB not persisted, cross-origin frames not walked, a small
keyboard table rather than Playwright's full layout.

## 3. Reproduce

```bash
uv sync
.venv/bin/python -m unittest -v tests/test_cli.py                          # Python daemon
BROWSER_CLI=$PWD/rust/target/release/browser BROWSER_DAEMON=$PWD/rust/target/release/browser-daemon \
  .venv/bin/python -m unittest -v tests/test_cli.py                        # Rust daemon
.venv/bin/python benchmarks/performance-test/run.py mychange 3 && .venv/bin/python benchmarks/performance-test/compare.py baseline final rust mychange
.venv/bin/python benchmarks/development-bench/harness.py setup t1_create_project     # then hand the prompt to a fresh agent
.venv/bin/python benchmarks/development-bench/harness.py verify t1_create_project run=mylabel
.venv/bin/python benchmarks/development-bench/harness.py passk
```
