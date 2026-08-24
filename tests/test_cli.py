"""End-to-end tests: real daemon + real CLI against the local test site in scratch/bench/site.

Run:  .venv/bin/python -m unittest -v tests/test_cli.py
"""
import json
import os
import re
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
SITE = ROOT / "scratch" / "bench" / "site"
def _free_port():
    import socket
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        return sk.getsockname()[1]


PORT = _free_port()
BASE = f"http://127.0.0.1:{PORT}"
SOCK = Path.home() / ".browser-daemon" / "socket"
ENV = {**os.environ, "PYTHONPATH": str(ROOT), "BROWSER_FREEZE_AFTER": "1"}


CLI = os.environ.get("BROWSER_CLI", "").split() or [PY, "-m", "cli.main"]  # e.g. BROWSER_CLI=rust/target/release/browser


def cli(*args, stdin=None):
    p = subprocess.run([*CLI, *args], capture_output=True, text=True, env=ENV, input=stdin)
    return p.returncode, p.stdout, p.stderr


def jcli(*args):
    rc, out, err = cli(*args)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"raw": out, "rc": rc, "stderr": err}


class DaemonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(["pkill", "-f", "daemon.server|browser-daemon|browser daemon"], capture_output=True)
        while subprocess.run(["pgrep", "-f", "daemon.server|browser-daemon|browser daemon"], capture_output=True).returncode == 0:
            time.sleep(0.1)
        SOCK.unlink(missing_ok=True)  # stale socket from a killed daemon
        cls.site = subprocess.Popen([PY, str(SITE / "server.py"), str(PORT)])
        daemon_cmd = os.environ.get("BROWSER_DAEMON", "").split() or [PY, "-m", "daemon.server"]  # e.g. rust/target/release/browser-daemon
        cls.daemon = subprocess.Popen(daemon_cmd, env=ENV, stdout=subprocess.DEVNULL, stderr=open("/tmp/test-daemon.log", "w"))
        deadline = time.time() + 15
        while not SOCK.exists() and time.time() < deadline:
            time.sleep(0.05)
        time.sleep(0.3)
        rc, out, err = cli("create")
        cls.sid = out.strip()
        assert re.fullmatch(r"[0-9a-f]{8}", cls.sid), (rc, out, err)

    @classmethod
    def tearDownClass(cls):
        cli(cls.sid, "delete")
        cli("shutdown")
        try:
            cls.daemon.wait(10)
        except subprocess.TimeoutExpired:
            cls.daemon.kill()
        cls.site.terminate()

    def setUp(self):
        r = jcli(self.sid, "navigate", f"{BASE}/dashboard.html")
        self.assertTrue(r["success"], r)

    # ---- navigation -------------------------------------------------------
    def test_navigate_spa_with_long_poll_is_fast_and_successful(self):
        t = time.perf_counter()
        r = jcli(self.sid, "navigate", f"{BASE}/dashboard.html")
        self.assertTrue(r["success"])
        self.assertLess(time.perf_counter() - t, 3.0)
        self.assertEqual(r["title"], "Bench Dashboard")

    def test_navigate_networkidle_never_fatal(self):
        r = jcli(self.sid, "navigate", f"{BASE}/dashboard.html", "--wait", "networkidle")
        self.assertTrue(r["success"])
        self.assertFalse(r["settled"])

    # ---- snapshot ---------------------------------------------------------
    def test_snapshot_shows_deep_interactive_elements_and_hides_invisible(self):
        rc, out, _ = cli(self.sid, "snapshot")
        self.assertEqual(rc, 0)
        self.assertIn('button "Create"', out)
        self.assertIn('textbox "Widget name"', out)
        self.assertIn('h1 "Turnstile"', out)
        self.assertNotIn("Accept", out)  # display:none consent tree
        self.assertNotIn('name="c1"', out)
        self.assertLess(len(out), 8000)

    def test_snapshot_scope_and_json(self):
        r = jcli(self.sid, "snapshot", "#create-form", "--json")
        self.assertTrue(r["success"])
        roles = [e["role"] for e in r["elements"]]
        self.assertEqual(roles, ["textbox", "combobox", "select", "button"])
        self.assertEqual(r["elements"][2]["options"], ["Managed", "Non-interactive"])
        self.assertTrue(all("box" in e and "ref" in e for e in r["elements"]))

    def test_refs_are_stable_across_snapshots(self):
        a = cli(self.sid, "snapshot")[1]
        b = cli(self.sid, "snapshot")[1]
        ref_a = re.search(r'(@e\d+) button "Create"', a).group(1)
        ref_b = re.search(r'(@e\d+) button "Create"', b).group(1)
        self.assertEqual(ref_a, ref_b)

    # ---- targeting --------------------------------------------------------
    def _status(self):
        return jcli(self.sid, "text", "#status")["text"]

    def test_click_by_ref(self):
        out = cli(self.sid, "snapshot")[1]
        ref = re.search(r'(@e\d+) button "Create"', out).group(1)
        self.assertTrue(jcli(self.sid, "type", "#wname", "zera-web")["success"])
        self.assertTrue(jcli(self.sid, "click", ref)["success"])
        self.assertEqual(self._status(), "Created widget zera-web")

    def test_click_by_text_and_role(self):
        self.assertTrue(jcli(self.sid, "click", "--text", "Create")["success"])
        self.assertIn("Created widget", self._status())
        self.assertTrue(jcli(self.sid, "click", "role=button[name=Ask AI]")["success"])
        self.assertIn("AI panel", self._status())

    def test_type_by_label_with_submit(self):
        self.assertTrue(jcli(self.sid, "type", "--label", "Hostname", "zera.example", "--submit")["success"])
        self.assertEqual(self._status(), "host set zera.example")

    def test_ambiguous_css_selector_is_refused_not_misclicked(self):
        r = jcli(self.sid, "click", "button.group.flex")
        self.assertFalse(r["success"])
        self.assertIn("strict mode", r["error"])
        self.assertEqual(self._status(), "")

    def test_stale_ref_errors_clearly(self):
        cli(self.sid, "snapshot")
        jcli(self.sid, "navigate", f"{BASE}/page2.html")
        r = jcli(self.sid, "click", "@e1")
        self.assertFalse(r["success"])
        self.assertIn("stale", r["error"])

    def test_select_by_label_and_value(self):
        self.assertTrue(jcli(self.sid, "select", "#mode", "Non-interactive")["success"])
        self.assertTrue(jcli(self.sid, "select", "#mode", "managed")["success"])
        r = jcli(self.sid, "snapshot", "#mode", "--json")
        self.assertEqual(r["elements"][0]["value"], "Managed")

    # ---- composite --------------------------------------------------------
    def test_action_with_inline_snapshot(self):
        rc, out, _ = cli(self.sid, "navigate", f"{BASE}/page2.html", "-s")
        self.assertEqual(rc, 0)
        self.assertIn('link "Back to dashboard"', out)

    def test_batch_runs_in_order_and_stops_on_failure(self):
        lines = '{"cmd":"type #wname batchy"}\n{"cmd":"click --text Create"}\n{"action":"text","params":{"selector":"#status"}}\n'
        rc, out, _ = cli(self.sid, "batch", stdin=lines)
        self.assertEqual(rc, 0, out)
        res = json.loads(out)["results"]
        self.assertEqual(res[-1]["text"], "Created widget batchy")
        lines = '{"cmd":"click #does-not-exist"}\n{"cmd":"click --text Create"}\n'
        rc, out, _ = cli(self.sid, "batch", stdin=lines)
        self.assertEqual(rc, 1)

    # ---- misc -------------------------------------------------------------
    def test_screenshot_is_private_and_viewport_sized(self):
        r = jcli(self.sid, "screenshot")
        self.assertTrue(r["success"])
        p = Path(r["path"])
        self.assertTrue(p.exists())
        self.assertEqual(oct(p.stat().st_mode & 0o777), "0o600")
        self.assertLess(r["bytes"], 150_000)
        p.unlink()

    def test_console_logs_are_captured(self):
        jcli(self.sid, "eval", "console.log('hello-from-test')")
        logs = jcli(self.sid, "console")["logs"]
        self.assertTrue(any(l["text"] == "hello-from-test" for l in logs))

    def test_list_is_json_and_reports_state(self):
        sessions = jcli("list")
        self.assertIsInstance(sessions, list)
        mine = [s for s in sessions if s["session_id"] == self.sid][0]
        self.assertIn(mine["state"], ("active", "frozen"))
        self.assertFalse(mine["visible"])

    def test_frozen_session_wakes_and_keeps_working(self):
        time.sleep(2.5)  # BROWSER_FREEZE_AFTER=1
        mine = [s for s in jcli("list") if s["session_id"] == self.sid][0]
        self.assertEqual(mine["state"], "frozen")
        self.assertTrue(jcli(self.sid, "click", "--text", "Create")["success"])
        self.assertIn("Created widget", self._status())

    def test_socket_permissions(self):
        self.assertEqual(oct(SOCK.stat().st_mode & 0o777), "0o600")


class CliParsingTests(unittest.TestCase):
    def test_capture_flag_parsing(self):
        from cli.main import parse_flags
        pos, f = parse_flags(["https://x", "-f", "-o", "out.jpg"], {"-f", "--full-page"}, {"-o", "--output"})
        self.assertEqual(pos, ["https://x"])
        self.assertEqual(f, {"f": True, "o": "out.jpg"})

    def test_build_requests(self):
        from cli.main import build
        self.assertEqual(build("s", "click", ["@e3", "-s"]), {"action": "click", "session_id": "s", "params": {"selector": "@e3", "snap": True}})
        self.assertEqual(build("s", "type", ["--label", "Name", "val"])["params"], {"selector": "", "text_value": "val", "label": "Name"})
        self.assertIsNone(build("s", "type", ["only-one-arg"]))
        self.assertEqual(build("s", "scroll", ["up", "300"])["params"], {"direction": "up", "amount": 300})


if __name__ == "__main__":
    unittest.main()
