import json, sys
from pathlib import Path
R = Path(__file__).parent / "results"
runs = [json.loads((R / f"{l}.json").read_text()) for l in sys.argv[1:]]
names = [r["label"] for r in runs]
print(f"{'metric':28s}" + "".join(f"{n:>16s}" for n in names))
def row(name, vals, fmt="{:.3f}"): print(f"{name:28s}" + "".join(f"{fmt.format(v) if v is not None else '-':>16s}" for v in vals))
row("daemon startup s", [r["startup_s"] for r in runs])
row("python floor s", [r["python_floor_s"] for r in runs])
for k in runs[0]["steps"]:
    row(f"{k} s", [r["steps"].get(k, {}).get("median_s") for r in runs])
for k in ("snapshot", "snapshot_scoped", "click_exact", "navigate_spa", "batch_4_ops"):
    row(f"{k} tokens", [r["steps"].get(k, {}).get("tokens") for r in runs], "{:.0f}")
row("screenshot KB", [r["steps"].get("screenshot", {}).get("file_kb") for r in runs], "{:.0f}")
row("TOTAL task s", [r["total_task_s"] for r in runs])
row("TOTAL task tokens", [r["total_task_tokens"] for r in runs], "{:.0f}")
row("idle CPU % (3-8s after cmd)", [r.get("idle_active", r["idle"])["cpu_pct"] for r in runs], "{:.1f}")
row("idle CPU % (parked >10s)", [r["idle"]["cpu_pct"] for r in runs], "{:.1f}")
row("idle GPU-proc %", [r["idle"]["gpu_pct"] for r in runs], "{:.1f}")
row("idle RSS MB", [r["idle"]["rss_mb"] for r in runs], "{:.0f}")
row("snapshot shows target", [r["steps"]["snapshot"].get("target_visible") for r in runs], "{}")
row("hidden consent leaked", [r["steps"]["snapshot"].get("hidden_consent_leaked") for r in runs], "{}")
row("ambiguous css click", ["/".join(sorted(set(r["correct"].get("ambiguous_click", ["wrong" if not all(r["correct"].get("ambiguous_click_hit_create", [0])) else "hit"])))) for r in runs], "{}")
row("click --text works", [all(r["correct"].get("click_text", [False])) for r in runs], "{}")
for k in ("click_ref", "navigate_with_snapshot", "batch_4_ops"):
    row(f"{k} ok", [r["steps"].get(k, {}).get("ok") for r in runs], "{}")
row("navigate+snapshot tokens", [r["steps"].get("navigate_with_snapshot", {}).get("tokens") for r in runs], "{:.0f}")
row("form flow correct", [all(r["correct"]["form_flow"]) for r in runs], "{}")
