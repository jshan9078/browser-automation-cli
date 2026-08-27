"""Deterministic admin app for agent benchmarks. State in memory; /__state and /__reset for verifiers."""
import http.server, json, os, sys, time, copy
from urllib.parse import urlparse, parse_qs
ROOT = os.path.dirname(os.path.abspath(__file__))
NAMES = ["Atlas","Borealis","Cascade","Delta","Echo","Falcon","Granite","Helix","Iris","Juniper","Kestrel","Lumen","Meridian","Nimbus","Orion","Pascal","Quartz","Rhea","Sierra","Tundra","Umbra","Vega","Willow","Xenon","Yarrow","Zephyr"]
def initial():
    projects = [{"id": i+1, "name": n, "hostname": f"{n.lower()}.example.com", "mode": ["managed","non-interactive","invisible"][i % 3],
                 "status": "active" if i % 4 != 3 else "archived", "owner": ["ana","ben","chen"][i % 3]} for i, n in enumerate(NAMES)]
    return {"projects": projects, "settings": {"digest": False, "timezone": "UTC", "display_name": "Acme Ops", "alerts": True},
            "account": {"email": "ops-admin@acme-internal.test", "plan": "Team"}, "logged_in": False, "events": [],
            "flags": {"new_dashboard": False, "beta_api": True, "dark_mode": False}, "tickets": [], "billing": {"email": "ap@acme-internal.test", "po": "PO-4471"},
            "priorities": ["Onboarding redesign", "SSO for enterprise", "Security patches", "Usage analytics", "Mobile app"], "schedule": {"date": None}, "export_code": None}
STATUS = [{"region": "us-east", "rate": 1.2}, {"region": "us-west", "rate": 0.4}, {"region": "eu-central", "rate": 3.7}, {"region": "ap-south", "rate": 2.9}, {"region": "sa-east", "rate": 0.8}]
AUDIT = [{"when": f"2026-08-{22 - i//6:02d} {23 - i%24:02d}:{(i*7)%60:02d}", "actor": ["ana","ben","chen","dara"][i % 4], "action": ["project.update","login","settings.update","member.invite"][i % 4], "target": ["Atlas","console","tz","eli@x"][i % 4]} for i in range(40)]
AUDIT[29] = {"when": "2026-08-18 04:12", "actor": "dara", "action": "api_key.delete", "target": "key_7f3a"}
STATE = initial()
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=ROOT, **k)
    def log_message(self, *a): pass
    def _json(self, obj, code=200):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def _body(self):
        n = int(self.headers.get("Content-Length") or 0); return json.loads(self.rfile.read(n) or b"{}")
    def _authed(self): return "session=ok" in (self.headers.get("Cookie") or "")
    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/__state": return self._json(STATE)
        if u.path == "/poll": time.sleep(25); self.send_response(204); self.end_headers(); return
        if u.path == "/api/me":
            return self._json(STATE["account"] if self._authed() else {"error": "unauthorized"}, 200 if self._authed() else 401)
        if u.path == "/api/projects":
            if not self._authed(): return self._json({"error": "unauthorized"}, 401)
            items = STATE["projects"]; s = (q.get("q", [""])[0]).lower()
            if s: items = [p for p in items if s in p["name"].lower() or s in p["hostname"]]
            page = int(q.get("page", ["1"])[0]); per = 8
            return self._json({"items": items[(page-1)*per:page*per], "total": len(items), "page": page, "pages": max(1, -(-len(items)//per))})
        if u.path == "/api/settings": return self._json(STATE["settings"])
        if u.path == "/api/status": return self._json(STATUS)
        if u.path == "/api/flags": return self._json(STATE["flags"])
        if u.path == "/api/billing": return self._json(STATE["billing"])
        if u.path == "/api/priorities": return self._json(STATE["priorities"])
        if u.path == "/api/schedule": return self._json(STATE["schedule"])
        if u.path == "/api/audit":
            page = int(q.get("page", ["1"])[0]); per = 12
            return self._json({"items": AUDIT[(page-1)*per:page*per], "page": page, "pages": -(-len(AUDIT)//per)})
        if u.path == "/": self.path = "/index.html"
        return super().do_GET()
    def do_POST(self):
        global STATE
        u = urlparse(self.path); body = self._body()
        if u.path == "/__reset": STATE = initial(); return self._json({"ok": True})
        if u.path == "/api/login":
            ok = body.get("username") == "ops-admin" and body.get("password") == "correct-horse"
            if ok: STATE["logged_in"] = True; self.send_response(200); self.send_header("Set-Cookie", "session=ok; Path=/"); self.send_header("Content-Type","application/json"); self.end_headers(); self.wfile.write(b'{"ok":true}'); return
            return self._json({"error": "Invalid username or password"}, 401)
        if not self._authed(): return self._json({"error": "unauthorized"}, 401)
        STATE["events"].append({"t": time.time(), "path": u.path, "body": body})
        if u.path == "/api/projects":
            pid = max([p["id"] for p in STATE["projects"]] + [0]) + 1
            p = {"id": pid, "name": body.get("name",""), "hostname": body.get("hostname",""), "mode": body.get("mode","managed"), "status": "active", "owner": "you"}
            STATE["projects"].append(p); return self._json(p, 201)
        if u.path.startswith("/api/projects/"):
            pid = int(u.path.split("/")[3]); p = next((x for x in STATE["projects"] if x["id"] == pid), None)
            if not p: return self._json({"error": "not found"}, 404)
            if u.path.endswith("/archive"): p["status"] = "archived"
            elif u.path.endswith("/restore"): p["status"] = "active"
            else: p.update({k: v for k, v in body.items() if k in ("name","hostname","mode")})
            return self._json(p)
        if u.path == "/api/tickets": STATE["tickets"].append(body); return self._json({"ok": True}, 201)
        if u.path == "/api/flags": STATE["flags"].update({k: bool(v) for k, v in body.items() if k in STATE["flags"]}); return self._json(STATE["flags"])
        if u.path == "/api/billing": STATE["billing"].update({k: v for k, v in body.items() if k in STATE["billing"]}); return self._json(STATE["billing"])
        if u.path == "/api/priorities": STATE["priorities"] = list(body.get("items", [])); return self._json(STATE["priorities"])
        if u.path == "/api/schedule": STATE["schedule"] = {"date": body.get("date")}; return self._json(STATE["schedule"])
        if u.path == "/api/audit/export":
            if body.get("password") != "correct-horse": return self._json({"error": "Incorrect password"}, 403)
            STATE["export_code"] = "EXP-" + hex(int(time.time()))[-5:].upper(); return self._json({"code": STATE["export_code"]})
        if u.path == "/api/settings": STATE["settings"].update({k: v for k, v in body.items() if k in STATE["settings"]}); return self._json(STATE["settings"])
        return self._json({"error": "unknown"}, 404)
http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8790), H).serve_forever()
