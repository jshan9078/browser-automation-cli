"""Snapshot size/latency on real pages. Usage: real_pages.py <label>"""
import json, os, subprocess, sys, time
sys.argv, _a = sys.argv[:1], sys.argv; import run as r; sys.argv = _a
label = sys.argv[1]
URLS = ["https://dash.cloudflare.com/login", "https://github.com/login", "https://news.ycombinator.com", "https://en.wikipedia.org/wiki/Playwright_(software)"]
subprocess.run(["pkill", "-f", "daemon.server|browser-daemon|browser daemon"], capture_output=True)
while subprocess.run(["pgrep", "-f", "daemon.server|browser-daemon|browser daemon"], capture_output=True).returncode == 0: time.sleep(0.1)
d = subprocess.Popen(r.DAEMON, env=r.ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
while not r.SOCK.exists(): time.sleep(0.05)
time.sleep(0.3)
res = {}
sid = r.cli("create")[1].strip()
for u in URLS:
    r.cli(sid, "navigate", u); time.sleep(2)
    dt, out, _ = r.cli(sid, "snapshot")
    has_login = any(k in out for k in ("Log in", "Sign in", "login", "Sign In")) or "ycombinator" in u or "wikipedia" in u
    res[u] = {"s": dt, "tokens": r.tokens(out), "lines": out.count("\n"), "mentions_login_or_content": has_login}
    (r.RESULTS / f"snap_{label}_{u.split('//')[1].split('/')[0]}.txt").write_text(out)
r.cli(sid, "delete"); d.terminate()
(r.RESULTS / f"real_{label}.json").write_text(json.dumps(res, indent=2))
for u, v in res.items(): print(f"{label:10s} {u[:45]:45s} {v['s']:.3f}s {v['tokens']:6d} tok")
