# BU Bench V1: results (browser-automation-cli + Claude Code)

Aggregate result for **browser-automation-cli + Claude Code** on
[BU Bench V1](https://github.com/browser-use/benchmark) (100 tasks, `opus-4-7`,
`gemini-2.5-flash` judge, their exact rubric). See `README.md` for the full fairness setup.

## Per-task scores

Published per task under `results/<task_id>/score.json`, **metadata only**: the judge verdict
(`score`, `votes`, `override`), category, and cost/token/timing metrics. See any file for the exact
shape.

> **What is deliberately NOT published.** BU Bench V1 is distributed **encrypted** so its tasks and
> gold answers stay secret. The full per-task record, `full.json` (agent `final_answer`, `reasoning`,
> and the gold `ground_truth`), agent traces (`trace.json`, `stream.txt`), and screenshots (`shots/`), > stays **local and git-ignored**; publishing it would leak the benchmark. The published `score.json`
> is stripped of all of that. To recompute, re-fetch the encrypted benchmark from browser-use/benchmark
> and run `run_suite.sh`.

## Headline

| metric | browser-automation-cli + Claude Code | BU: Claude Code + Browser Harness |
|---|---|---|
| Accuracy (ground-truth-verified) | **87 / 100** | 74 |
| Raw `gemini-2.5-flash` judge (identical to BU) | **82 / 100** | 74 |

Same 100 tasks, same judge model and rubric, same `opus-4-7`, default thinking, only the
browser tool differs (browser-automation-cli vs BU's browser-harness).

## By category (ground-truth-verified, /20 each)

| category | score |
|---|---|
| BrowseComp | 15 / 20 |
| GAIA | 17 / 20 |
| InteractionTests | 20 / 20 |
| OM2W2 | 17 / 20 |
| WebBenchREAD | 18 / 20 |

## Notes on scoring

- The judge (`gemini-2.5-flash`, temperature 0.5) is non-deterministic, so each task is
  judged **3×** and the majority verdict is taken (vote splits stored locally).
- Ground-truth verification corrected **5 raw-judge errors** (a judge current-date
  hallucination plus gold-answer format mismatches). Per-task detail is withheld to keep
  the encrypted tasks/answers private. This lifts the raw 82 → verified 87.
- BU's published 74 is **not** similarly corrected (they publish no per-task data), so it
  carries the same judge noise our raw 82 does.
