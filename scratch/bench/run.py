"""Benchmark harness for browser-cli.
Usage: .venv/bin/python scratch/bench/run.py <label> [--iters N] [--cli-extra ...]
Starts the local test site + the daemon from the working tree, drives it through the CLI,
and writes scratch/bench/results/<label>.json. Same script runs before/after every change.
"""
import json, os, re, statistics, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
PY = str(ROOT / ".venv/bin/python")
CLI = os.environ.get("BROWSER_CLI", "").split() or [PY, "-m", "cli.main"]          # e.g. rust/target/release/browser
DAEMON = os.environ.get("BROWSER_DAEMON", "").split() or [PY, "-m", "daemon.server"]
SITE = Path(__file__).parent / "site"
PORT = 8765
RESULTS = Path(__file__).parent / "results"; RESULTS.mkdir(exist_ok=True)
SOCK = Path.home() / ".browser-daemon" / "socket"
ENV = {**os.environ, "PYTHONPATH": str(ROOT)}

def cli(*args):
    t = time.perf_counter()
    p = subprocess.run([*CLI, *args], capture_output=True, text=True, env=ENV)
    return time.perf_counter() - t, p.stdout, p.stderr

def procs():
    out = subprocess.run(["ps", "-Ao", "pid,ppid,pcpu,rss,comm"], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 4)
        if len(parts) == 5: rows.append((int(parts[0]), int(parts[1]), float(parts[2]), int(parts[3]), parts[4]))
    return rows

def descendants(root):
    out = subprocess.run(["ps", "-Ao", "pid,ppid"], capture_output=True, text=True).stdout
    kids = {}
    for line in out.splitlines()[1:]:
        a = line.split()
        if len(a) == 2: kids.setdefault(int(a[1]), []).append(int(a[0]))
    res, stack = set(), [root]
    while stack:
        x = stack.pop(); res.add(x); stack.extend(kids.get(x, []))
    return res

def cputimes(pids):
    out = subprocess.run(["ps", "-o", "pid,time,rss,comm", "-p", ",".join(map(str, pids))], capture_output=True, text=True).stdout
    res = {}
    for line in out.splitlines()[1:]:
        a = line.split(None, 3)
        if len(a) < 4: continue
        t = a[1]; parts = t.split(":"); secs = float(parts[-1]) + 60 * int(parts[-2]) + (3600 * int(parts[-3]) if len(parts) > 2 else 0)
        res[int(a[0])] = (secs, int(a[2]), a[3])
    return res

def chrome_stats(root, interval=5):
    """CPU% of the daemon's whole process tree (python + all Chromium helpers) over `interval` s."""
    pids = descendants(root)
    a = cputimes(pids); time.sleep(interval); b = cputimes(pids)
    cpu = gpu = rss = 0.0
    for pid in b:
        if pid in a:
            d = (b[pid][0] - a[pid][0]) / interval * 100
            cpu += d; rss += b[pid][1] / 1024
            if "GPU" in b[pid][2]: gpu += d
    return {"cpu": cpu, "gpu": gpu, "rss_mb": rss, "n": len(b)}

def tokens(s): return round(len(s) / 4)  # approx; consistent across runs

def main():
    label = sys.argv[1]; iters = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    # --- start site + daemon
    site = subprocess.Popen([PY, str(SITE / "server.py"), str(PORT)])
    subprocess.run(["pkill", "-f", "daemon.server|browser-daemon|browser daemon"], capture_output=True)
    while subprocess.run(["pgrep", "-f", "daemon.server|browser-daemon|browser daemon"], capture_output=True).returncode == 0: time.sleep(0.1)
    if SOCK.exists(): SOCK.unlink()
    t0 = time.perf_counter()
    daemon = subprocess.Popen(DAEMON, env=ENV, stdout=subprocess.DEVNULL, stderr=open(RESULTS / f"{label}.daemon.log", "w"))
    while not SOCK.exists(): time.sleep(0.05)
    time.sleep(0.3)
    startup = time.perf_counter() - t0
    res = {"label": label, "startup_s": startup, "steps": {}, "correct": {}, "iters": iters}
    steps = {}
    def rec(name, dt, out, extra=None):
        steps.setdefault(name, []).append({"s": dt, "bytes": len(out), "tokens": tokens(out), **(extra or {})})

    try:
        # python interpreter floor
        t = time.perf_counter(); subprocess.run([PY, "-c", "pass"]); res["python_floor_s"] = time.perf_counter() - t
        base = f"http://127.0.0.1:{PORT}"
        for it in range(iters):
            dt, out, err = cli("create"); sid = out.strip(); rec("create", dt, out)
            dt, out, _ = cli(sid, "navigate", f"{base}/dashboard.html"); rec("navigate_spa", dt, out, {"ok": '"success": true' in out})
            dt, out, _ = cli(sid, "snapshot"); rec("snapshot", dt, out, {"target_visible": "create-btn" in out or '"Create"' in out, "hidden_consent_leaked": 'name="c1"' in out or '"c1"' in out})
            # ambiguous selector (what an agent derived from the old snapshot)
            dt, out, _ = cli(sid, "click", "button.group.flex"); rec("click_ambiguous", dt, out)
            _, st, _ = cli(sid, "snapshot", "#status")
            res["correct"].setdefault("ambiguous_click", []).append("hit" if "Created" in st else "refused" if "WRONG" not in st else "wrong")
            # --- new-API steps (fail on old code; recorded as n/a)
            dt, out, _ = cli(sid, "click", "--text", "Create"); rec("click_text", dt, out, {"ok": '"success": true' in out})
            _, st, _ = cli(sid, "text", "#status"); res["correct"].setdefault("click_text", []).append("Created" in st)
            dt, out, _ = cli(sid, "snapshot"); m = re.search(r'(@e\d+) button "Create"', out); ref = m.group(1) if m else "@e0"
            dt, out, _ = cli(sid, "click", ref); rec("click_ref", dt, out, {"ok": '"success": true' in out})
            dt, out, _ = cli(sid, "navigate", f"{base}/dashboard.html", "-s"); rec("navigate_with_snapshot", dt, out, {"ok": "@e" in out})
            t = time.perf_counter()
            p = subprocess.run([*CLI, sid, "batch"], input='{"cmd":"type #wname batchy"}\n{"cmd":"type #host h.example"}\n{"cmd":"click --text Create"}\n{"action":"text","params":{"selector":"#status"}}\n', capture_output=True, text=True, env=ENV)
            rec("batch_4_ops", time.perf_counter() - t, p.stdout, {"ok": "Created widget batchy" in p.stdout})
            dt, out, _ = cli(sid, "type", "#wname", "zera-web"); rec("type", dt, out)
            dt, out, _ = cli(sid, "type", "#host", "zera.example"); rec("type", dt, out)
            dt, out, _ = cli(sid, "press", "Enter"); rec("press", dt, out)
            dt, out, _ = cli(sid, "click", "#create-btn"); rec("click_exact", dt, out)
            dt, out, _ = cli(sid, "snapshot", "#status"); rec("snapshot_scoped", dt, out); res["correct"].setdefault("form_flow", []).append("Created widget zera-web" in out)
            dt, out, _ = cli(sid, "navigate", f"{base}/page2.html"); rec("navigate_static", dt, out)
            dt, out, _ = cli(sid, "back"); rec("back", dt, out)
            dt, out, _ = cli(sid, "screenshot"); rec("screenshot", dt, out)
            m = re.search(r'"path": "([^"]+)"', out); shot = Path(m.group(1)) if m else None
            if shot and shot.exists(): steps["screenshot"][-1]["file_kb"] = shot.stat().st_size / 1024
            dt, out, _ = cli("list"); rec("list", dt, out)
            if it < iters - 1: cli(sid, "delete")
        # idle resource sample with one session parked on the dashboard (what the user sees while agent "thinks")
        idle_url = os.environ.get("BENCH_IDLE_URL", f"{base}/dashboard.html")
        cli(sid, "navigate", idle_url); time.sleep(3)
        active = chrome_stats(daemon.pid)  # 3-8 s after the last command: page still running
        res["idle_active"] = {"cpu_pct": active["cpu"], "gpu_pct": active["gpu"], "rss_mb": active["rss_mb"]}
        time.sleep(float(os.environ.get("BROWSER_FREEZE_AFTER", "10")) + 2)  # past the freeze threshold (old code: no freeze)
        samples = [chrome_stats(daemon.pid) for _ in range(3)]
        med = lambda k: statistics.median(s[k] for s in samples)
        res["idle"] = {"cpu_pct": med("cpu"), "gpu_pct": med("gpu"), "rss_mb": med("rss_mb"), "procs": samples[-1]["n"]}
        # idle after 60s quiet (does anything throttle/freeze?)
        cli(sid, "delete")
    finally:
        daemon.terminate(); site.terminate()
        try: daemon.wait(5)
        except Exception: daemon.kill()

    for k, v in steps.items():
        res["steps"][k] = {"median_s": statistics.median(x["s"] for x in v), "bytes": statistics.median(x["bytes"] for x in v), "tokens": statistics.median(x["tokens"] for x in v),
                           **{kk: v[0][kk] for kk in v[0] if kk not in ("s", "bytes", "tokens")}}
    res["total_task_s"] = sum(res["steps"][k]["median_s"] for k in res["steps"])
    res["total_task_tokens"] = sum(res["steps"][k]["tokens"] for k in res["steps"])
    (RESULTS / f"{label}.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    main()
