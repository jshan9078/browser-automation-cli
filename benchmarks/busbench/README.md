# busbench — browser-automation-cli vs Browser Use on BU Bench V1

Runs **BU Bench V1** (browser-use/benchmark, 100 tasks) with **Claude Code + browser-automation-cli**,
scored by **their exact judge** (`gemini-2.5-flash`, verbatim rubric from their `judge.py`), so our
number is directly comparable to their published bars. We do NOT run Browser Use's paid cloud tool —
we compare to their committed results.

## Fairness setup (matches how they ran)
- **Model:** `claude-opus-4-7` (their Claude bars' model; verified runnable via Claude Code).
- **Thinking level:** **default** — they pass no `--effort`, so we omit it too. (Set `EFFORT=high` to sweep, as a bonus — not the headline.)
- **`claude -p` flags:** `--max-turns 100 --dangerously-skip-permissions --output-format stream-json --verbose --append-system-prompt-file system_prompt.md` — same shape as their `claude_code_harness`. Only the browser tool differs (browser-cli vs their browser-harness) and the tool's instructions (`/browser-cli` skill vs their system prompt).
- **Judge:** `gemini-2.5-flash`, their prompt/rubric/schema, sees task + trajectory + ground truth + last 10 screenshots → binary verdict. Same judge that produced their published numbers. **Per-call config verified identical to BU's** (from browser-use 0.11.5 `ChatGoogle` source): `temperature=0.5`, dynamic thinking (`thinking_budget=-1`), structured output (`response_schema=JudgementResult` + `application/json`), no seed. Rubric+flags+response-format diff-identical to their `judge.py`.
- **3× majority vote:** BU's judge is non-deterministic (temp 0.5) — single-run verdicts swing on borderline tasks (we observed the same task drawing `[True, False, True]`). We call the identical judge **3× per task and take the majority**, storing the vote split. This cuts single-run noise the way BU's own multiple full-suite runs (their chart error bars) do. Tunable via `JUDGE_VOTES`. Final scoring is one consistent pass via `./rejudge_all.sh` after capture.
- **No task logins needed** — BU Bench V1 runs logged-out (verified). Tasks run on ephemeral browser-cli sessions.

## Published targets (their gemini-2.5-flash judge, /100)
| framework (opus-4-7) | score |
|---|---|
| Claude Code + Browser Harness | **74** ← our direct drop-in comparison |
| Browser Use 0.13.7 | 74 |
| Claude Code + Agent Browser (chart) | 77 |
| Browser Use Cloud v3 (chart) | 78 |
| BrowserCode 0.0.3 | 86 (chart: 89.5 @ opus-4-8) |

## Prereqs (run in YOUR terminal)
1. **Claude auth**: `CLAUDE_CODE_OAUTH_TOKEN` — auto-loaded from repo-root `.env` (or `CLAUDE_KEY`), same as webbench.
2. **Judge via your GCP credits (Vertex)** — VALIDATED working (2026-08-25) on `gemini-2.5-flash`:
   ```bash
   gcloud auth application-default login        # log in (YOU do this)
   gcloud auth application-default set-quota-project <PROJECT-WITH-CREDITS>
   export GOOGLE_CLOUD_PROJECT=<PROJECT-WITH-CREDITS> GOOGLE_CLOUD_LOCATION=us-central1
   ```
   Use the project you actually have credits/permissions on as BOTH the quota project and
   `GOOGLE_CLOUD_PROJECT` (the default gcloud project may lack `serviceusage.services.use`).
   The judge uses `genai.Client(vertexai=True, …)` with ADC when `GOOGLE_CLOUD_PROJECT` is set;
   `gemini-2.5-flash` is available on Vertex even though AI Studio blocks it for new users.
   *Alternative (AI Studio):* `export GOOGLE_API_KEY=…` instead (no GCP).

## Run
```bash
./run_suite.sh 10                 # pilot: 10 tasks
./run_suite.sh InteractionTests   # one category (20)
./run_suite.sh all                # all 100
```
Per-task raw bundles → `raw/`, judged results → `results/`, summary via `python3 report.py`. Resumable
(skips already-judged tasks).


## Capture now, judge later (decoupled)
Every run persists everything the judge needs — `raw/<id>.json` (answer, full agent_steps, ground truth,
metrics), `raw/<id>.stream.txt` (transcript), `raw/shots/<id>/*.png` (screenshots), and a headless
per-task video `raw/video/<id>.mp4` — so judging never re-runs the model, and we never re-run the
expensive opus pass just to get footage.

**Video (on by default):** reuses webbench's `record_cdp.py` — a headless Chrome DevTools screencast
(no visible window) attached to the run's tab, assembled to mp4 via ffmpeg. It does NOT affect the score
(the judge reads only screenshots) or the token/step/cost metrics; only adds a few MB/task + minor
wall-clock. Set `RECORD=0` to skip. Needs `ffmpeg` + the `websockets` python package.
```bash
NO_JUDGE=1 ./run_suite.sh all      # capture all 100 now (no Google creds needed)
JUDGE_ONLY=1 ./run_suite.sh        # judge every captured bundle later (needs GOOGLE_* creds)
```

## Judge model availability (important)
BU's judge is `gemini-2.5-flash`. On **AI Studio it's blocked for new users** ("use gemini-3.6-flash").
To keep BU's EXACT judge (for comparable numbers), use **Vertex/GCP**, where 2.5-flash persists:
`gcloud auth application-default login` + `export GOOGLE_CLOUD_PROJECT=… GOOGLE_CLOUD_LOCATION=us-central1`.
Override with `JUDGE_MODEL=…` only if 2.5-flash is truly unavailable — and disclose the judge change
(their published numbers were gemini-2.5-flash).

## Files
`loader.py` (decrypt tasks — public key), `system_prompt.md` (our harness prompt), `run_task.py`
(Claude Code + browser-cli, one task → raw bundle w/ answer, trajectory, screenshots, metrics),
`judge_runner.py` (their gemini-2.5-flash judge, verbatim rubric), `run_suite.sh`, `report.py`,
`judge_bu.py` + `system_prompt_bu_reference.md` (vendored from their repo for reference).

## Do not commit run data
`raw/` and `results/` contain decrypted BU Bench task text + ground-truth answers. Per browser-use's
request (don't publish plaintext / don't train on it), these are **gitignored**. `BU_Bench_V1.enc` is
their public encrypted file.

## Resumability / crash recovery
The suite is idempotent — **to resume after any crash, just re-run the same command** (`MODEL=… GOOGLE_CLOUD_PROJECT=… ./run_suite.sh all`). Skip rules:
- `results/<id>.json` exists → task fully done, skipped.
- `raw/<id>.json` exists (captured, not judged) → run skipped, judge re-attempted.
- Neither exists → task runs fresh.

Crash safety in `run_task.py`: a genuine crash (process died / no result object / claude `error_during_execution`) writes a `raw/<id>.error.json` marker and exits nonzero **without** writing `raw/<id>.json`, so resume re-runs it instead of locking in a spurious FAIL. A legit `error_max_turns` outcome IS kept and judged (a real failure, like BU). The bundle is written atomically (`.tmp` + `os.replace`) so a mid-write crash never leaves a partial JSON. Judge failures (e.g. Vertex blip) keep the raw bundle → re-judge later with `JUDGE_ONLY=1 ./run_suite.sh`.

## Browser-tier confound: anti-bot / captcha (IMPORTANT)
BU's benchmark browsers are **cloud browsers with residential proxies + captcha solvers + stealth**
default-on (see their `browsers/`: browserbase `solveCaptchas`, steel `solveCaptcha`, anchor
`captcha_solver+extra_stealth`, onkernel reCAPTCHA solver, BrowserUseCloud stealth server-side). Their
own **Stealth Bench** measures the gap: `browser-use-cloud 73.8%` vs `local_headful 50%` vs
`local_headless 3.8%` anti-bot pass. **browser-cli's default is `local_headless`** — the 3.8% tier — so
tasks gated by PerimeterX/DataDome/Akamai/login-walls fail on *infrastructure*, not agent capability
(~29% of our tasks hit this). This understates our accuracy vs their cloud-browser bars.

**EMPIRICAL FINDING (headed does NOT fix it):** a direct A/B probe (`scratchpad/headed_probe.sh`) navigating
headed browser-cli to the blocked pages showed StreetEasy still returns PerimeterX "Press & Hold" and
apartments.com still returns Akamai "Access Denied" — even headed, even on a residential Mac IP. The
Stealth Bench `local_headful 50%` is an average buoyed by easy sites; the hard blocks our tasks hit
(PerimeterX/Akamai/DataDome) key on IP reputation + TLS/behavioral fingerprinting, so a local browser
fails whether headless or headed. The real differentiator is BU's **residential proxy + captcha solver**,
which local browser-cli lacks. `HEADED=1` and `./rerun_headed_blocked.sh` still exist but are LOW-YIELD
on these sites — don't spend opus on them.

Reporting mitigation instead:
- `report.py` prints an **infra-adjusted accuracy** = accuracy EXCLUDING judge-flagged captcha/blocked/
  impossible tasks (the "agent capability where the page was reachable" number) alongside the raw number.
- Disclose plainly: browser-cli is a local browser with no proxy/captcha-solver; N tasks lost to anti-bot
  walls BU's cloud browsers pass by design.

## Caveats to disclose in any writeup
- Their Claude Code version at run time (~2026-04) is unknown (passthrough); record your `claude --version`.
- Single-run judge variance is real (their sonnet runs swung 61–69) — do ≥2 runs.
- Their browser tool is a *remote* cloud browser; browser-cli is *local* (affects latency/resource metrics).
- **We omit their `--max-budget-usd 10` cap** (running on a CC subscription). That cap could early-terminate a task as a FAIL on their side; ours runs to `--max-turns 100`. Slightly favors us — disclose.
- **`--bare` divergence:** they ran `--bare` (no skill); our token auth needs it off, so the `/browser-cli` skill loads. Different system context. The hardened `system_prompt.md` forbids daemon/session management to compensate.
- **Screenshots are agent-driven**, not auto-captured per step like an agent-browser harness — the judge sees only shots the agent chose to take (pilot: 2–8/task). Fewer images = less visual evidence for the judge.
- `agent_steps` are per-step truncated (assistant 500 / tool-input 200 / result 300 chars) to build the trajectory the judge reads — a compressed view vs BU's native format.
- Lead with Pareto: their Claude Code harness spent ~$97 / 6,245 steps for 74% — efficiency is browser-cli's likely edge.
