"""Agent benchmark orchestration.
  harness.py setup <task>            -> resets app, (re)starts daemon, creates session, prints the agent prompt
  harness.py verify <task> [answer]  -> judges the task from app state / answer, computes metrics, writes results/<task>.<run>.json
  harness.py report                  -> table over results/
"""
import json, os, re, statistics, subprocess, sys, time, urllib.request
from pathlib import Path
HERE = Path(__file__).resolve().parent; ROOT = HERE.parents[1]
PY = str(ROOT / ".venv/bin/python"); PORT = 8790
CLI = os.environ.get("BROWSER_CLI", "").split() or [PY, "-m", "cli.main"]
DAEMON = os.environ.get("BROWSER_DAEMON", "").split() or [PY, "-m", "daemon.server"]; BASE = f"http://127.0.0.1:{PORT}"
SOCK = Path.home() / ".browser-daemon" / "socket"; RES = HERE / "results"; RES.mkdir(exist_ok=True)
LOG = HERE / "results" / "calls.log"; META = HERE / "results" / "current.json"
ENV = {**os.environ, "PYTHONPATH": str(ROOT)}
sys.path.insert(0, str(ROOT / "scratch/bench")); _argv = sys.argv; sys.argv = sys.argv[:1]; import run as bench; sys.argv = _argv

def state(): return json.load(urllib.request.urlopen(f"{BASE}/__state"))
def proj(st, name): return next((p for p in st["projects"] if p["name"] == name), None)

LOGIN = "The console requires signing in: username `ops-admin`, password `correct-horse` (test credentials, fine to type)."
TASKS = {
  "t1_create_project": {
    "prompt": f"In the Acme Console at {BASE}/ create a new project named `zera-web` with hostname `zera.example.com` and widget mode `Non-interactive`. {LOGIN} Finish when the project appears in the Projects list.",
    "verify": lambda st, ans: (p := proj(st, "zera-web")) is not None and p["hostname"] == "zera.example.com" and p["mode"] == "non-interactive" and p["status"] == "active"},
  "t2_archive_project": {
    "prompt": f"In the Acme Console at {BASE}/ archive the project named `Orion` (it is not on the first page of the Projects list). Confirm the archive dialog. {LOGIN} Do not archive any other project.",
    "verify": lambda st, ans: proj(st, "Orion")["status"] == "archived" and sum(p["status"] == "archived" for p in st["projects"]) == 7},
  "t3_settings": {
    "prompt": f"In the Acme Console at {BASE}/ open Settings, enable the 'Weekly digest email' checkbox, set Timezone to `Europe/Berlin`, leave everything else unchanged, and save. {LOGIN}",
    "verify": lambda st, ans: st["settings"] == {"digest": True, "timezone": "Europe/Berlin", "display_name": "Acme Ops", "alerts": True}},
  "t4_rename": {
    "prompt": f"In the Acme Console at {BASE}/ rename the project `Atlas` to `Atlas v2` using the rename (pencil) control in the Projects list, and save. {LOGIN}",
    "verify": lambda st, ans: proj(st, "Atlas v2") is not None and proj(st, "Atlas") is None and len(st["projects"]) == 26},
  "t5_extract_count": {
    "prompt": f"In the Acme Console at {BASE}/ determine how many projects currently have status `archived` across ALL pages of the Projects list (the list is paginated). {LOGIN} Reply with the final line `ANSWER: <number>`.",
    "verify": lambda st, ans: (ans or "").strip() == "6"},
  "t6_extract_account": {
    "prompt": f"In the Acme Console at {BASE}/ find the account email address shown on the Dashboard after signing in. {LOGIN} Reply with the final line `ANSWER: <email>`.",
    "verify": lambda st, ans: (ans or "").strip().lower() == "ops-admin@acme-internal.test"},
  # ---- hard tier: each forces a different observation/interaction strategy
  "h1_canvas_chart": {"prompt": f"In the Acme Console at {BASE}/ open the Status page and determine which region has the HIGHEST error rate in the chart. {LOGIN} Reply with the final line `ANSWER: <region>`.",
    "verify": lambda st, ans: (ans or "").strip().lower() == "eu-central"},
  "h2_iframe_ticket": {"prompt": f"In the Acme Console at {BASE}/ open Support and submit a support ticket with subject `Turnstile widget not rendering`, priority `High`, and any short description. {LOGIN}",
    "verify": lambda st, ans: any(t.get("subject") == "Turnstile widget not rendering" and t.get("priority") == "High" for t in st["tickets"])},
  "h3_shadow_flags": {"prompt": f"In the Acme Console at {BASE}/ open Feature flags, turn ON `New dashboard`, leave the other flags unchanged, and save. {LOGIN}",
    "verify": lambda st, ans: st["flags"] == {"new_dashboard": True, "beta_api": True, "dark_mode": False}},
  "h4_audit_delayed": {"prompt": f"In the Acme Console at {BASE}/ open the Audit log and find who performed the `api_key.delete` action (the log loads slowly and is paginated with a Load more button). {LOGIN} Reply with the final line `ANSWER: <actor>`.",
    "verify": lambda st, ans: (ans or "").strip().lower() == "dara"},
  "h5_banner_overlay": {"prompt": f"In the Acme Console at {BASE}/ open Billing, change the billing email to `finance@acme-internal.test` (leave the PO number), and save. {LOGIN}",
    "verify": lambda st, ans: st["billing"] == {"email": "finance@acme-internal.test", "po": "PO-4471"}},
  "h6_infinite_scroll": {"prompt": f"In the Acme Console at {BASE}/ open Members and find the role of the member named `Priya Natarajan` (the list loads more as you scroll). {LOGIN} Reply with the final line `ANSWER: <role>`.",
    "verify": lambda st, ans: (ans or "").strip().lower() == "billing"},
  "h7_reorder": {"prompt": f"In the Acme Console at {BASE}/ open Priorities and move `Security patches` to the TOP of the list, keeping the relative order of the others, then save. {LOGIN}",
    "verify": lambda st, ans: st["priorities"] == ["Security patches", "Onboarding redesign", "SSO for enterprise", "Usage analytics", "Mobile app"]},
  "h8_datepicker": {"prompt": f"In the Acme Console at {BASE}/ open Maintenance and schedule the maintenance window for October 14, 2026 using the calendar, then save. {LOGIN}",
    "verify": lambda st, ans: st["schedule"].get("date") == "2026-10-14"},
  "h9_reauth_export": {"prompt": f"In the Acme Console at {BASE}/ open the Audit log (it loads slowly), click Export log, complete the confirmation, and report the confirmation code shown. {LOGIN} Reply with the final line `ANSWER: <code>`.",
    "verify": lambda st, ans: st["export_code"] is not None and (ans or "").strip().upper() == st["export_code"]},
  "h10_validation": {"prompt": f"In the Acme Console at {BASE}/ open Settings and set Display name to `Acme Ops Platform Team EMEA`, then save. If the app rejects the value, use the longest prefix it accepts (do not change other settings). {LOGIN}",
    "verify": lambda st, ans: st["settings"]["display_name"] == "Acme Ops Platform Te" and st["settings"]["timezone"] == "UTC"},
  "t7_live_wikipedia": {
    "prompt": "Using the browser, open https://en.wikipedia.org/wiki/Playwright_(software) and find the programming language(s) listed in the infobox 'Written in' row. Reply with the final line `ANSWER: <languages>`.",
    "verify": lambda st, ans: "typescript" in (ans or "").lower()},
}
AGENT_RULES = f"""You are operating a web browser through the `browser` CLI (use ONLY this tool, via Bash; never use Playwright/curl/fetch or the app's HTTP API directly, never read the app's source code; interact through the UI as a user would. Screenshots are allowed and sometimes necessary; `eval` is allowed for reading the DOM).
Run `browser --help` once if you need the command reference. A session already exists: `browser {{sid}} <command>`. Headless; you cannot see the screen except via `browser {{sid}} snapshot` (text, cheap) or `browser {{sid}} screenshot` (image file, expensive).
Work efficiently: prefer snapshot refs (@eN) and --text/--label targets, use `-s` to get a snapshot with an action, and `batch` for known sequences. Do not create or delete sessions. When done, reply with a one-line summary (and `ANSWER: ...` as the last line if asked)."""

def ensure_daemon():
    def alive(): return subprocess.run(["pgrep", "-f", "daemon.server|browser-daemon"], capture_output=True).returncode == 0
    if alive() and not SOCK.exists():  # a daemon is shutting down; let it finish
        for _ in range(100):
            if not alive(): break
            time.sleep(0.1)
    if not SOCK.exists() or not alive():
        SOCK.unlink(missing_ok=True)
        subprocess.Popen(DAEMON, env=ENV, stdout=subprocess.DEVNULL, stderr=open(RES / "daemon.log", "a"))
        while not SOCK.exists(): time.sleep(0.05)
        time.sleep(0.3)
    try: urllib.request.urlopen(f"{BASE}/__state", timeout=1)
    except Exception:
        subprocess.Popen([PY, str(HERE / "app/server.py"), str(PORT)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(0.5)

def daemon_pid():
    out = subprocess.run(["pgrep", "-f", "daemon.server|browser-daemon"], capture_output=True, text=True).stdout.split()
    return int(out[0]) if out else None

def tree_cpu(pid):
    pids = bench.descendants(pid); t = bench.cputimes(pids)
    return {"cpu_s": sum(v[0] for v in t.values()), "rss_mb": sum(v[1] for v in t.values()) / 1024, "pids": {str(k): v[0] for k, v in t.items()}}

def setup(task):
    ensure_daemon()
    urllib.request.urlopen(urllib.request.Request(f"{BASE}/__reset", data=b"{}", method="POST"))
    for s in json.loads(subprocess.run([*CLI, "list"], capture_output=True, text=True, env=ENV).stdout):
        subprocess.run([*CLI, s["session_id"], "delete"], capture_output=True, env=ENV)
    create = [*CLI, "create"] + (["--show"] if os.environ.get("BENCH_VISIBLE") else [])  # BENCH_VISIBLE=1: headed window
    sid = subprocess.run(create, capture_output=True, text=True, env=ENV).stdout.strip()
    LOG.write_text("")
    META.write_text(json.dumps({"task": task, "sid": sid, "t0": time.time(), "cpu0": tree_cpu(daemon_pid()), "visible": bool(os.environ.get("BENCH_VISIBLE"))}))
    print(AGENT_RULES.format(sid=sid) + "\n\nTASK: " + TASKS[task]["prompt"] + f"\n\nSet the environment variable AGENTBENCH_LOG={LOG} and use the `browser` binary at {HERE}/bin/browser (e.g. `export PATH={HERE}/bin:$PATH`).")

def verify(task, answer=None, agent_tokens=None, run=None):
    meta = json.loads(META.read_text()); t1 = time.time(); cpu1 = tree_cpu(daemon_pid())
    # daemon-side request log is the source of truth (agents may bypass the shim); shim log adds stdout size when present
    rlog = Path.home() / ".browser-daemon" / "requests.log"
    calls = []
    for l in rlog.read_text().splitlines() if rlog.exists() else []:
        e = json.loads(l)
        if e["t"] >= meta["t0"] and e.get("session") == meta["sid"]:
            calls.append({"t": e["t"], "dur": e["dur"], "rc": 0 if e["ok"] else 1, "out_chars": e["bytes"],
                          "args": [meta["sid"], e["action"]] + ([json.dumps(e["params"])[:60]] if e.get("params") else []) + (["batch:" + ",".join(e["batch"])] if e.get("batch") else [])})
    st = state(); ok = False
    try: ok = bool(TASKS[task]["verify"](st, answer))
    except Exception as e: ok = False
    # CPU: sum over pids present at both samples (+ full time of pids that appeared)
    used = sum(cpu1["pids"][p] - meta["cpu0"]["pids"].get(p, 0.0) for p in cpu1["pids"])
    r = {"task": task, "run": run or time.strftime("%H%M%S"), "success": ok, "answer": answer, "visible": meta.get("visible", False),
         "wall_s": round((calls[-1]["t"] + calls[-1]["dur"] - calls[0]["t"]) if calls else 0, 2),
         "wall_total_s": round(t1 - meta["t0"], 1),
         "cli_calls": len(calls), "failed_calls": sum(c["rc"] != 0 for c in calls),
         "cli_time_s": round(sum(c["dur"] for c in calls), 2),
         "tool_output_tokens": round(sum(c["out_chars"] for c in calls) / 4),
         "snapshots": sum("snapshot" in " ".join(c["args"]) or '"snap": true' in " ".join(c["args"]) for c in calls), "screenshots": sum("screenshot" in c["args"] for c in calls),
         "daemon_cpu_s": round(used, 2), "daemon_rss_mb": round(cpu1["rss_mb"]), "agent_tokens": agent_tokens,
         "commands": [" ".join(c["args"][1:])[:80] for c in calls]}
    (RES / f"{task}.{r['run']}.json").write_text(json.dumps(r, indent=2)); print(json.dumps({k: v for k, v in r.items() if k != "commands"}, indent=1)); return r

def report():
    rows = [json.loads(f.read_text()) for f in sorted(RES.glob("[th]*.json"))]
    hdr = f"{'task':22s} {'run':8s} {'ok':4s} {'calls':>5s} {'fail':>4s} {'wall s':>7s} {'cli s':>6s} {'tool tok':>8s} {'agent tok':>9s} {'cpu s':>6s} {'rss MB':>6s}"
    print(hdr)
    for r in rows: print(f"{r['task']:22s} {r['run']:8s} {'PASS' if r['success'] else 'FAIL':4s} {r['cli_calls']:5d} {r['failed_calls']:4d} {r['wall_s']:7.1f} {r['cli_time_s']:6.2f} {r['tool_output_tokens']:8d} {str(r.get('agent_tokens') or '-'):>9s} {r['daemon_cpu_s']:6.1f} {r['daemon_rss_mb']:6d}")
    if rows:
        print(f"\nsuccess {sum(r['success'] for r in rows)}/{len(rows)} · median calls {statistics.median(r['cli_calls'] for r in rows)} · median wall {statistics.median(r['wall_s'] for r in rows):.1f}s · total tool tokens {sum(r['tool_output_tokens'] for r in rows)}")

def passk():
    """pass@k per implementation: attempts are runs labelled <impl> and <impl>-N."""
    import statistics as st
    rows = [json.loads(f.read_text()) for f in sorted(RES.glob("[th]*.json")) if "contaminated" not in f.name and "headed" not in f.name]
    impls = {"python (sonnet)": "sonnet", "rust (sonnet)": "rust", "rust 0.4.0 pypi (haiku)": "haiku"}
    print(f"{'impl':16s} {'tasks':>5s} {'attempts':>8s} {'pass@1':>7s} {'pass@2':>7s} {'med calls':>9s} {'med fail':>8s} {'med wall':>8s} {'med cli s':>9s} {'med tool tok':>12s} {'med agent tok':>13s} {'med cpu s':>9s} {'med rss':>7s}")
    for name, prefix in impls.items():
        att = [r for r in rows if r["run"] == prefix or r["run"].startswith(prefix + "-")]
        tasks = sorted({r["task"] for r in att})
        p1 = sum(all(r["success"] for r in att if r["task"] == t) for t in tasks)  # every attempt passed
        p2 = sum(any(r["success"] for r in att if r["task"] == t) for t in tasks)
        med = lambda k: st.median(r[k] for r in att)
        print(f"{name:16s} {len(tasks):5d} {len(att):8d} {p1:4d}/{len(tasks):<2d} {p2:4d}/{len(tasks):<2d} {med('cli_calls'):9.0f} {med('failed_calls'):8.0f} {med('wall_s'):8.1f} {med('cli_time_s'):9.2f} {med('tool_output_tokens'):12.0f} {med('agent_tokens'):13.0f} {med('daemon_cpu_s'):9.2f} {med('daemon_rss_mb'):7.0f}")
        print(f"{'':16s} totals: calls {sum(r['cli_calls'] for r in att)}, failed {sum(r['failed_calls'] for r in att)}, wall {sum(r['wall_s'] for r in att):.0f} s, tool tok {sum(r['tool_output_tokens'] for r in att):,}, agent tok {sum(r['agent_tokens'] or 0 for r in att):,}")
    print("\nper task (calls / wall s / failed) attempt1 | attempt2:")
    for t in sorted({r["task"] for r in rows}, key=lambda x: (x[0] != 't', int(''.join(c for c in x.split('_')[0] if c.isdigit())))):
        cells = []
        for prefix in ("sonnet", "rust", "haiku"):
            a = [r for r in rows if r["task"] == t and (r["run"] == prefix or r["run"].startswith(prefix + "-"))]
            a.sort(key=lambda r: r["run"])
            cells.append(" | ".join(f"{'P' if r['success'] else 'F'} {r['cli_calls']}/{r['wall_s']:.0f}/{r['failed_calls']}" for r in a))
        print(f"  {t:22s} python: {cells[0]:28s} rust: {cells[1]:28s} haiku: {cells[2]}")

if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "setup": setup(sys.argv[2])
    elif cmd == "verify":
        kw = {}; args = sys.argv[3:]
        ans = next((a.split("=",1)[1] for a in args if a.startswith("answer=")), None)
        tok = next((int(a.split("=",1)[1]) for a in args if a.startswith("tokens=")), None)
        run = next((a.split("=",1)[1] for a in args if a.startswith("run=")), None)
        verify(sys.argv[2], ans, tok, run)
    elif cmd == "report": report()
    elif cmd == "passk": passk()
    elif cmd == "tasks": print("\n".join(TASKS))
