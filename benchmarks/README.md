# benchmarks/

Three benchmarks, each answering a different question. Two axes separate them: whether a real **LLM
agent** drives the tool (vs a fixed script), and **what** they measure.

| dir | question it answers | driver | environment | measures | judge |
|---|---|---|---|---|---|
| `performance-test/` | Is the *tool* fast and lean? | scripted CLI (no LLM) | local test site | per-command latency, snapshot tokens, idle CPU/RSS, cold start | none, deterministic timing |
| `development-bench/` | Does an agent *correctly* drive the tool through hard UI? | fresh LLM subagents | local synthetic app | pass@1/@2 over 17 tasks, calls, tokens | deterministic verifier functions |
| `busbench/` | How do we *rank vs other tools*? | LLM agent (Claude Code) | real external sites, browser-use's 100 encrypted tasks | accuracy /100 | browser-use's `gemini-2.5-flash` judge + rubric |

> **web-bench moved out.** The efficiency benchmark (model × thinking-level × harness cost on live
> sites like Amazon and X) now lives in its own repo: **https://github.com/jshan9078/web-bench**. It
> drives this tool but isn't part of it.

## performance-test/: tool performance (regression guard)

`run.py` runs the **same scripted command sequence** every time against a local test site
(`performance-test/site`), so any change in latency / snapshot tokens / idle CPU / RSS is the tool's
own doing. It's the source of the "Technical Details" numbers (~2 ms/command, ~245 tokens/snapshot,
~2% idle CPU, ~0.4 s cold start). `compare.py <labels…>` diffs runs (e.g. `baseline` vs `rust`). No
LLM involved, this is pure tool benchmarking, run before/after every change.

## development-bench/: agent correctness (internal, reproducible)

17 tasks run by **fresh LLM subagents** against a self-hosted synthetic admin app (login gate,
iframes, shadow DOM, infinite scroll, datepickers, canvas). Every answer is checked by an exact
**verifier function**, so scoring is fully deterministic and free of live-site drift. This is the
"did I break agent-driving?" suite (the "17/17 pass@2" claim). The app is synthetic → no PII, no
third-party IP → the whole suite (including results) is published.

## busbench/: external comparison (BU Bench V1)

Runs [browser-use's standardized 100-task benchmark](https://github.com/browser-use/benchmark) with
Claude Code + browser-automation-cli, scored by **their** exact `gemini-2.5-flash` judge and rubric,
so the number is directly comparable to their published bars.

> The benchmark is distributed **encrypted** to keep its tasks and gold answers secret. Only the
> methodology (`README.md`), the sanitized aggregate (`RESULTS.md`), and per-task **metadata-only**
> scores (`results/<task_id>/score.json`) are published. The full per-task record, answers,
> ground-truth, agent traces, and screenshots, is git-ignored and never committed. To recompute,
> re-fetch the encrypted benchmark from browser-use/benchmark and run `run_suite.sh`.

## performance-test vs development-bench

Both run locally, but performance-test is *scripted* (measures tool speed) while development-bench
uses *real LLM agents* (measures whether agents can correctly operate the tool). Different apps,
different question: **speed vs correctness**.
