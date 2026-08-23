# Agent benchmark — real tasks, programmatic verifiers

Measures what matters for an agent tool: **can a fresh LLM agent, given only the `browser` CLI,
complete realistic tasks**, and at what cost in calls, time, tokens and hardware. Companion to
[OPTIMIZATION.md](OPTIMIZATION.md) (which measures the tool in isolation). Harness in
`scratch/agentbench/`; raw results in `scratch/agentbench/results/*.json`.

## Method

- **Environment** — a deterministic local admin app (`scratch/agentbench/app/`): login gate,
  searchable paginated table, 2-step wizard with autocomplete, settings form, confirm modal, inline
  rename, plus a *hard tier* where each page forces a different strategy (below). The server keeps
  state in memory and exposes `/__state` + `/__reset` to the harness only. One live-site task
  (Wikipedia) is included for external realism.
- **Verifiers** — every task is judged from **application state** (or, for extraction tasks, an
  `ANSWER:` line compared to ground truth), never from what the agent says it did.
- **Agent** — a fresh subagent per task (Claude Sonnet; three early runs on the orchestrator's own
  model are kept, labelled `fable`), given only: the rules, the session id, the task text. It has
  no access to this repo's docs beyond `browser --help`, and no memory between tasks. The
  orchestrator never sees the agent's transcript, only its final line — results are not inflated by
  the orchestrator's context.
- **Metrics** — success; CLI calls and failed calls; wall-clock from first to last call; CLI time
  (sum of call durations — exposes timeouts); tool-output tokens (bytes the agent had to read ÷ 4);
  agent tokens (total context consumed by the subagent, from its usage report); daemon CPU-seconds
  and RSS over the task (process tree, `ps -o time` deltas). Calls are counted from the **daemon's
  own request log** (`~/.browser-daemon/requests.log`) — a PATH shim proved unreliable because one
  agent found the globally installed `browser` instead.
- **Run**: `harness.py setup <task>` → give the printed prompt to a fresh agent → `harness.py verify
  <task> [answer=…] [tokens=…] [run=label]` → `harness.py report`.

### Hard tier — what each task forces

| task | forces |
|---|---|
| h1 canvas chart: "which region has the highest error rate" | **screenshot** (data exists only as pixels) |
| h2 support form inside a same-origin **iframe** | snapshot cannot see frames |
| h3 feature-flag toggle inside **shadow DOM** | snapshot cannot see shadow roots |
| h4 audit log: 3 s delayed load, "Load more" pagination, target on page 3 | waiting + multi-page search |
| h5 billing: announcement **banner overlays** the Save button after 1.5 s | intercepted click → dismiss |
| h6 **infinite scroll** members list, target ~4 loads down | scrolling strategy |
| h7 **drag-and-drop** reorder (keyboard alternative only in an aria hint) | reading a11y hints; no drag command exists |
| h8 **calendar date picker**, no typing | multi-click navigation |
| h9 export requires **password re-confirmation** modal, then a one-time code | multi-step dialog + extraction |
| h10 display-name **validation** (max 20 chars) | noticing an error, recovering |

## Results (v0.3.0, 2026-08-22)

| task | model | ok | calls | failed | wall s | CLI s | tool tok | agent tok | daemon CPU s |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| t1 create project (wizard) | sonnet | PASS | 19 | 4 | 45.8 | 2.3 | 2,283 | 50,406 | 0.9 |
| t2 archive Orion (page 2 + modal) | sonnet | PASS | 20 | 5 | 36.3 | 1.8 | 1,208 | 48,654 | 0.7 |
| t3 settings (checkbox + select) | sonnet | PASS | 11 | 0 | 27.6 | 0.7 | 1,153 | 44,574 | 0.7 |
| t4 inline rename | sonnet | PASS | 12 | 2 | 20.2 | 1.3 | 1,150 | 45,209 | 0.6 |
| t5 count archived across 4 pages | sonnet | PASS | 17 | 0 | 34.5 | 1.7 | 2,208 | 45,754 | 0.6 |
| t6 extract account email | sonnet | PASS | 9 | 0 | 15.6 | 0.8 | 955 | 42,539 | 0.8 |
| t7 live Wikipedia infobox | sonnet | PASS | 3 | 1 | 8.0 | 0.8 | 141 | 41,879 | 0.4 |
| h1 canvas chart (screenshot) | sonnet | PASS | 16 | 5 | 27.7 | 1.3 | 644 | 48,600 | 0.6 |
| **h2 iframe ticket** | sonnet | PASS | **438** | 21 | **330.7** | 95.5 | **11,151** | 62,236 | 6.1 |
| h3 shadow DOM flags | sonnet | PASS | 18 | 1 | 63.1 | 1.8 | 1,314 | 47,568 | 0.8 |
| h4 delayed + paginated audit | sonnet | PASS | 20 | 5 | 40.8 | 1.8 | 726 | 47,828 | 0.9 |
| h5 banner overlay | sonnet | PASS | 22 | 6 | 54.0 | 12.0 | 2,751 | 52,242 | 1.3 |
| h6 infinite scroll | sonnet | PASS | 26 | 2 | 27.6 | 2.4 | 1,040 | 45,127 | 0.8 |
| h7 reorder (keyboard hint) | sonnet | PASS | 15 | 2 | 33.8 | 1.8 | 1,236 | 46,285 | 0.7 |
| h8 date picker | sonnet | PASS | 13 | 2 | 33.3 | 1.5 | 2,358 | 49,199 | 0.6 |
| h9 re-auth + code | sonnet | PASS | 17 | 4 | 31.9 | 1.6 | 1,077 | 47,297 | 0.9 |
| h10 validation recovery | sonnet | PASS | 17 | 2 | 63.2 | 21.8 | 1,534 | 47,006 | 1.1 |

**17/17 tasks pass.** Excluding h2: median 17 calls, 33 s wall, 1.2k tool tokens, ~47k agent tokens,
0.8 daemon-CPU-seconds per task; daemon RSS ≈ 450 MB throughout. Three tasks also ran on the
orchestrator's model for reference (t1–t3, `fable` rows in `harness.py report`): same pass rate,
fewer calls, but ~30 s of CLI time each from 10 s `wait` timeouts.

Baseline note: v0.2.1 cannot run this suite as-is (its snapshot omits the form and the
`button.group.flex` click hits the wrong button — see OPTIMIZATION.md), so there is no older
agent-level row; this table is the baseline for future rewrites.

### Rust daemon (v0.4.0-alpha), all 17 tasks, same Sonnet subagents

| task | Python calls / wall / failed / tool tok | Rust calls / wall / failed / tool tok |
|---|---|---|
| t1_create_project | 19 / 46 s / 4 / 2,283 | 16 / 47 s / 0 / 2,352 |
| t2_archive_project | 20 / 36 s / 5 / 1,208 | 15 / 29 s / 0 / 1,338 |
| t3_settings | 11 / 28 s / 0 / 1,153 | 10 / 22 s / 0 / 1,134 |
| t4_rename | 12 / 20 s / 2 / 1,150 | 9 / 20 s / 0 / 1,288 |
| t5_extract_count | 17 / 35 s / 0 / 2,208 | 17 / 60 s / 3 / 2,285 |
| t6_extract_account | 9 / 16 s / 0 / 955 | 8 / 35 s / 0 / 440 |
| t7_live_wikipedia | 3 / 8 s / 1 / 141 | 2 / 4 s / 0 / 47 |
| h1_canvas_chart | 16 / 28 s / 5 / 644 | 9 / 26 s / 0 / 687 |
| h2_iframe_ticket | 438 / 331 s / 21 / 11,151 | 9 / 12 s / 0 / 801 |
| h3_shadow_flags | 18 / 63 s / 1 / 1,314 | 8 / 19 s / 0 / 923 |
| h4_audit_delayed | 20 / 41 s / 5 / 726 | 13 / 35 s / 0 / 1,980 |
| h5_banner_overlay | 22 / 54 s / 6 / 2,751 | 12 / 46 s / 2 / 2,526 |
| h6_infinite_scroll | 26 / 28 s / 2 / 1,040 | 47 / 23 s / 0 / 932 |
| h7_reorder | 15 / 34 s / 2 / 1,236 | 14 / 33 s / 2 / 2,411 |
| h8_datepicker | 13 / 33 s / 2 / 2,358 | 18 / 33 s / 1 / 2,271 |
| h9_reauth_export | 17 / 32 s / 4 / 1,077 | 13 / 32 s / 0 / 1,151 |
| h10_validation | 17 / 63 s / 2 / 1,534 | 11 / 26 s / 0 / 1,195 |

Totals over 17 tasks — calls 693 → 231, failed calls 62 → 8, tool-output tokens 32,929 → 23,761; 17/17 pass on both. Screenshots were used in h1 only (1 each, headless — `Page.captureScreenshot` renders
off-screen, so headless does not prevent screenshot-based tasks). h6 on Rust is 47 calls because the
agent polled with `eval` 37 times while scrolling — not a daemon cost (1.4 s CLI time total). A first
h1 Rust run (46 calls) is kept as `h1_canvas_chart.rust-contaminated.json`: the agent invoked the stale
global `browser` 0.2.1 whose `type` payload the new daemon misread; the daemon now accepts the legacy
payload and the global install was updated.

Headed data point (`BENCH_VISIBLE=1`, a visible window): h1 canvas chart PASS, 30 calls, 126 s, 1 screenshot, daemon RSS 1380 MB. The extra calls were login retries: typed text was dropped because a non-frontmost window has no document focus — fixed afterwards with `Emulation.setFocusEmulationEnabled` (tests pass; the headed task has not been re-run since).

## pass@2 (2026-08-23): two independent attempts per task, both implementations, Sonnet

Second attempt of every task on both daemons (`harness.py passk`). Rows labelled `sonnet`/`rust` are
attempt 1, `sonnet-2`/`rust-2` attempt 2. Python h5 has three rows because the first run predates the
overlay fix to the scenario itself.

```
impl             tasks attempts  pass@1  pass@2 med calls med fail med wall med cli s med tool tok med agent tok med cpu s med rss
python (sonnet)     17       35   17/17   17/17        16        1     33.8      1.37         1545         47006      0.79     452
                 totals: calls 958, failed 72, wall 1765 s, tool tok 80,393, agent tok 1,706,103
rust                17       34   17/17   17/17        12        0     28.1      0.55         1298         45032      0.46     375
                 totals: calls 483, failed 14, wall 1110 s, tool tok 50,048, agent tok 1,547,341

per task (calls / wall s / failed) attempt1 | attempt2:
  t1_create_project      python: P 19/46/4 | P 20/58/0        rust: P 16/47/0 | P 17/45/0
  t2_archive_project     python: P 20/36/5 | P 11/31/0        rust: P 15/29/0 | P 10/26/0
  t3_settings            python: P 11/28/0 | P 11/24/0        rust: P 10/22/0 | P 9/20/0
  t4_rename              python: P 12/20/2 | P 14/33/0        rust: P 9/20/0 | P 7/15/0
  t5_extract_count       python: P 17/35/0 | P 16/39/0        rust: P 17/60/3 | P 17/32/0
  t6_extract_account     python: P 9/16/0 | P 7/12/0          rust: P 8/35/0 | P 8/16/1
  t7_live_wikipedia      python: P 3/8/1 | P 3/7/0            rust: P 2/4/0 | P 2/4/0
  h1_canvas_chart        python: P 16/28/5 | P 8/23/0         rust: P 9/26/0 | P 11/21/0
  h2_iframe_ticket       python: P 438/331/21 | P 27/237/4    rust: P 9/12/0 | P 10/13/0
  h3_shadow_flags        python: P 18/63/1 | P 18/66/1        rust: P 8/19/0 | P 8/12/0
  h4_audit_delayed       python: P 20/41/5 | P 20/59/2        rust: P 13/35/0 | P 23/199/2
  h5_banner_overlay      python: P 11/24/0 | P 22/54/6 | P 16/51/1 rust: P 12/46/2 | P 12/27/2
  h6_infinite_scroll     python: P 26/28/2 | P 21/27/0        rust: P 47/23/0 | P 68/35/0
  h7_reorder             python: P 15/34/2 | P 13/36/1        rust: P 14/33/2 | P 13/36/1
  h8_datepicker          python: P 13/33/2 | P 19/53/1        rust: P 18/33/1 | P 14/30/0
  h9_reauth_export       python: P 17/32/4 | P 13/28/0        rust: P 13/32/0 | P 11/32/0
  h10_validation         python: P 17/63/2 | P 17/63/0        rust: P 11/26/0 | P 12/44/0
```

Reading: **pass@1 = 17/17 and pass@2 = 17/17 for both implementations** — no task failed in any
attempt on either daemon, so the rewrite did not cost accuracy. Where they differ is cost: Rust does
the same work with **half the CLI calls (958 → 483), a fifth of the failed calls (72 → 14), 37 %
less wall time, 38 % fewer tool-output tokens and ~9 % fewer agent tokens**, with lower daemon CPU
(0.46 vs 0.79 s median) and RSS (375 vs 452 MB). The iframe task is the clearest case: Python 438
and 27 calls (331 s, 237 s — the second attempt worked around the gap by navigating to the frame
URL), Rust 9 and 10 calls (12–13 s). Variance is real on both sides (h4 on Rust: 35 s then 199 s
from the agent's own long `wait`s; h6 on Rust: 47 and 68 calls of `eval` polling) — which is why two
attempts per task is the minimum for judging a change.

## What the runs revealed

1. **Iframes are the one real capability gap.** h2 succeeded only because the agent tabbed into the
   frame and typed the subject *one keypress per CLI call* (`press T`, `press u`, …): 438 calls,
   5.5 minutes, 9× the tool tokens of any other task. Playwright can address frames
   (`frame_locator`); the snapshot and targeting need to include same-origin frames.
2. **Shadow DOM is fine in practice**: the snapshot omits it, but `eval` revealed the structure and
   Playwright CSS selectors pierce shadow roots, so `click acme-toggle … input` worked (18 calls).
   Worth listing shadow-root content in the snapshot anyway to save the detour.
3. **Screenshots were used only when necessary** (h1: 1; h2/h3: 1–2 while exploring). Agents
   default to the text snapshot — the token-efficiency design holds under real use.
4. **Failed calls are mostly CLI-ergonomics misses**, not page problems: `fill` instead of `type`
   (6 of 17 runs), flags before the action (`-s click @e3`), guessed `batch` formats (JSON arrays).
   Each costs one ~50 ms round-trip and a re-read of `--help`. Cheap fixes: alias `fill`, accept
   flags in any position, show a `batch` example in `--help`.
5. **Timeouts dominate CLI time where it is high**: h10 (21.8 s) and h5 (12 s) include 10 s waits
   for elements that never appeared. A shorter default (`--timeout`) for `wait`/`click` when the
   agent is exploring would cut wall time without affecting success.
6. **Agent tokens are dominated by the agent's own context (~40k floor)**, not by tool output
   (1–2k). Reducing calls per task is therefore the lever for both latency and cost — `-s` and
   `batch` usage was inconsistent; the `--help` text should push them harder.

## Next

- Fix the ergonomics misses (fill alias, flag order, batch help) and add frame support; re-run the
  suite — the expected movement is h2 from 438 → ~20 calls and failed calls roughly halved.
- Add scenarios not yet covered: multi-tab (`target=_blank`), file upload, a cross-origin iframe,
  an OAuth-style redirect chain, and a `show`-then-`hide` login hand-off.
- Run each task 3× to get variance before using the suite to judge a rewrite.
