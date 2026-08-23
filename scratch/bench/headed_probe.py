import json, subprocess, sys, time
sys.argv, _a = sys.argv[:1], sys.argv; import run as r; sys.argv = _a
subprocess.run(["pkill","-f","daemon.server|browser-daemon"],capture_output=True)
while subprocess.run(["pgrep","-f","daemon.server|browser-daemon"],capture_output=True).returncode==0: time.sleep(0.1)
r.SOCK.unlink(missing_ok=True)
site = subprocess.Popen([r.PY, str(r.SITE/"server.py"), "8765"])
d = subprocess.Popen(r.DAEMON,env=r.ENV,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
while not r.SOCK.exists(): time.sleep(0.05)
time.sleep(0.3)
sid = r.cli("create","--show")[1].strip(); print("shown session", sid)
# per-command latency in headed mode
for args in (("navigate","http://127.0.0.1:8765/dashboard.html"),("snapshot",),("click","--text","Create"),("type","#wname","x"),("screenshot",)):
    dt,out,_ = r.cli(sid,*args); print(f"  headed {args[0]:10s} {dt:.3f}s {len(out)} bytes")
# idle CPU headed on Cloudflare (never frozen while visible)
r.cli(sid,"navigate","https://dash.cloudflare.com/login"); time.sleep(3)
a = r.chrome_stats(d.pid); time.sleep(12); b = r.chrome_stats(d.pid)
print(f"  headed parked on Cloudflare: 3-8s {a['cpu']:.0f}% (gpu {a['gpu']:.0f}%), >15s {b['cpu']:.0f}%, rss {b['rss_mb']:.0f}MB")
# auth hand-off: set cookie + localStorage while shown, hide, check from headless
r.cli(sid,"navigate","http://127.0.0.1:8765/dashboard.html")
r.cli(sid,"eval","document.cookie='auth=secret123; path=/'; localStorage.setItem('tok','abc'); 1")
print("  hide ->", r.cli(sid,"hide")[1].strip().replace("\n",""))
time.sleep(14)  # let it freeze
st = [s for s in json.loads(r.cli("list")[1]) if s["session_id"]==sid][0]; print("  state after hide+14s:", st["state"], "visible:", st["visible"])
out = json.loads(r.cli(sid,"eval","document.cookie + '|' + localStorage.getItem('tok')")[1]); print("  hidden sees:", out["result"])
b2 = r.chrome_stats(d.pid); print(f"  after hide, parked: {b2['cpu']:.0f}% rss {b2['rss_mb']:.0f}MB")
print("  show again ->", r.cli(sid,"show")[1].strip().replace("\n",""))
out = json.loads(r.cli(sid,"eval","document.cookie + '|' + localStorage.getItem('tok')")[1]); print("  shown sees:", out["result"])
r.cli(sid,"delete"); r.cli("shutdown"); site.terminate()
