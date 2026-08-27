# BU Bench V1 — results (browser-automation-cli + Claude Code)

Aggregate result for **browser-automation-cli + Claude Code** on
[BU Bench V1](https://github.com/browser-use/benchmark) (100 tasks, `opus-4-7`,
`gemini-2.5-flash` judge — their exact rubric). See `README.md` for the full fairness setup.

> **Why no per-task files here.** BU Bench V1 is distributed **encrypted**
> (`BU_Bench_V1.enc`) so its tasks and gold answers stay secret. Our per-task result
> files contain the decrypted task content, agent answers, reasoning, and (for some
> tasks) the gold `ground_truth`. Publishing them would leak the benchmark, so they are
> git-ignored (`results/`, `raw/`) and never committed. Only this aggregate + the harness
> code are published. To recompute, decrypt the benchmark yourself and run `run_suite.sh`.

## Headline

| metric | browser-automation-cli + Claude Code | BU: Claude Code + Browser Harness |
|---|---|---|
| Accuracy (ground-truth-verified) | **87 / 100** | 74 |
| Raw `gemini-2.5-flash` judge (identical to BU) | **82 / 100** | 74 |

Same 100 tasks, same judge model and rubric, same `opus-4-7`, default thinking — only the
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
