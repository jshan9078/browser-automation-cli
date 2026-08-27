#!/usr/bin/env python3
"""Summarize our run vs BU Bench V1's published aggregates on the SAME axes they report:
accuracy, steps (their num_steps = assistant blocks + tool_results, == our len(agent_steps)),
steps/task, and duration. Joins results/ (judge verdicts) with raw/ (metrics) by task_id.

Note on step parity: BU's num_steps counts each assistant content block (text + each tool_use) plus
each tool_result — exactly what steps_from_stream() builds — so len(agent_steps) is the comparable
metric, NOT cli_calls (browser calls only). Duration: ours is local wall time around the claude run;
BU's cloud runs include remote-browser latency (not apples-to-apples on absolute seconds).
"""
import json, glob, collections
from pathlib import Path

# Published BU Bench V1 aggregates pulled from browser-use/benchmark result JSONs (100 tasks each).
# (acc%, total_steps, total_duration_s, total_cost_usd, source_dir). cost 0 = not logged (cloud).
PUBLISHED = {
    "BrowserCode 0.0.3 (opus-4-7)":            (86.0, 5093, 40115, 150, "old_results"),
    "Claude Code + Browser Harness (opus-4-7)": (74.0, 6245, 35993,  97, "old_results"),  # our drop-in bar
    "Browser Use 0.13.7 native (opus-4-7)":     (74.0, 1984, 47810,   0, "official"),
    "Browser Use 0.11.7 (opus-4-7)":            (65.0, 1793, 30472,   0, "old_results"),
    "Browser Use Cloud v3 / bu-ultra (chart)":  (78.0, 1623, 25881, 134, "old_results"),
}
# chart-only bars with NO committed result file: Agent Browser 77, BU Local gpt-5.5 68, Stagehand 51;
# BrowserCode chart 89.5 (opus-4-8) vs committed 86 (opus-4-7).

results = {json.loads(Path(f).read_text())["task_id"]: json.loads(Path(f).read_text())
           for f in glob.glob("results/*.json")}
raws = {json.loads(Path(f).read_text())["task_id"]: json.loads(Path(f).read_text())
        for f in glob.glob("raw/*.json") if ".error." not in f}
ids = [t for t in results if t in raws]
if not ids:
    print("no judged results with raw bundles yet"); raise SystemExit

import statistics
n = len(ids)
passed = sum(results[t]["score"] for t in ids)          # majority-vote pass count (denoised view)
# BU-comparable estimator: each judge draw is one single-judge scoring of the suite (their per-run
# method). Report the MEAN pass-rate across draws ± std (their averaging + error-bar methodology).
# A task passing 2/3 contributes 0.667 — an UNBIASED estimate of the single-judge score, unlike
# majority vote which sharpens toward 0/1. (Our error bar is judge-only variance; theirs also
# includes agent re-run variance since they re-run the agent each full run.)
V = max((len(results[t].get("votes") or [None]) for t in ids), default=1)
draw_rates = []
for i in range(V):
    hits = 0
    for t in ids:
        vs = results[t].get("votes")
        v = (vs[i] if vs and i < len(vs) else (vs[-1] if vs else bool(results[t]["score"])))
        hits += 1 if v else 0
    draw_rates.append(100 * hits / n)
mean_rate = statistics.mean(draw_rates)
std_rate = statistics.pstdev(draw_rates) if len(draw_rates) > 1 else 0.0
steps = [len(raws[t].get("agent_steps", [])) for t in ids]
walls = [raws[t].get("wall_s") or 0 for t in ids]
clis = [raws[t].get("cli_calls") or 0 for t in ids]
toks = [raws[t].get("agent_tokens") or 0 for t in ids]
costs = [raws[t].get("cost_usd") or 0 for t in ids]
tot_steps, tot_wall = sum(steps), sum(walls)

model = raws[ids[0]].get("model"); effort = raws[ids[0]].get("effort")
print(f"OURS: Claude Code + browser-cli  ({model}, effort={effort})   [{n}/100 tasks judged]")
print(f"  accuracy:     {mean_rate:.1f}% ± {std_rate:.1f}   (mean±std over {V} judge draws — BU-comparable)")
print(f"                per-draw rates: {[round(x,1) for x in draw_rates]}   [judge-only variance]")
print(f"  (majority-vote denoised view: {passed}/{n} = {100*passed/n:.1f}%)")
# infra-adjusted: exclude tasks the judge flagged as captcha/blocked/impossible — anti-bot walls that
# BU's cloud browsers (residential proxy + captcha solver) pass by design and local browser-cli can't.
blocked = [t for t in ids if results[t].get("reached_captcha") or results[t].get("impossible_task")]
nb = [t for t in ids if t not in set(blocked)]
if blocked:
    nb_pass = sum(results[t]["score"] for t in nb)
    print(f"  infra-adjusted: {100*nb_pass/len(nb):.1f}%  ({nb_pass}/{len(nb)}, excl. {len(blocked)} anti-bot/blocked tasks)"
          f"   [agent capability where the page was reachable]")
bycat = collections.defaultdict(lambda: [0, 0])
for t in ids:
    bycat[results[t]["category"]][0] += results[t]["score"]; bycat[results[t]["category"]][1] += 1
print("  by category:  " + ", ".join(f"{c} {p}/{tt}" for c, (p, tt) in sorted(bycat.items())))
print(f"  steps:        {tot_steps} total · {tot_steps/n:.1f}/task"
      f"   (proj. 100-task: {tot_steps/n*100:.0f})   [len(agent_steps), == BU num_steps]")
print(f"  duration:     {tot_wall/60:.1f} min total · {tot_wall/n:.0f}s/task"
      f"   (proj. 100-task: {tot_wall/n*100/60:.0f} min)   [local wall; BU incl. remote browser]")
print(f"  browser CLI:  {sum(clis)} total · {sum(clis)/n:.1f}/task   [our extra: browser actions only]")
print(f"  tokens:       {sum(toks)/1e6:.1f}M total · {sum(toks)/n/1e3:.0f}k/task")
print(f"  cost (CC's own figure, not headline): ${sum(costs):.2f} total · ${sum(costs)/n:.2f}/task")
caps = sum(1 for t in ids if results[t].get("reached_captcha"))
imp = sum(1 for t in ids if results[t].get("impossible_task"))
if caps or imp:
    print(f"  judge flags:  {caps} captcha, {imp} impossible")

print(f"\nPUBLISHED (BU Bench V1, same gemini-2.5-flash judge, 100 tasks):")
print(f"  {'framework':<42}{'acc%':>6}{'steps':>7}{'st/task':>8}{'dur/task':>9}{'cost':>7}")
for k, (acc, st, dur, cost, src) in PUBLISHED.items():
    print(f"  {k:<42}{acc:>6.1f}{st:>7}{st/100:>8.1f}{dur/100:>8.0f}s{('$'+str(cost)) if cost else '-':>7}")
print(f"\n  ours (mean±std): {'':<25}{mean_rate:>6.1f}{tot_steps/n*100:>7.0f}{tot_steps/n:>8.1f}{tot_wall/n:>8.0f}s   (±{std_rate:.1f})")
print(f"\nAccuracy is the headline; steps/task & duration/task are the efficiency axes. Our drop-in bar is")
print(f"'Claude Code + Browser Harness' (74%, 62 steps/task, ${97} for 100) — same claude -p, only the")
print(f"browser tool swapped. chart-only bars (Agent Browser 77, BU-Local 68, Stagehand 51) have no data file.")
