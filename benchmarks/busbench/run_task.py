#!/usr/bin/env python3
"""Run ONE BU Bench V1 task with Claude Code + browser-automation-cli, capturing everything the judge
needs (final answer, agent trajectory, screenshots) plus efficiency metrics. Writes raw/<task_id>.json.

  python3 run_task.py <task_id> [effort]     # effort optional; OMIT to match BU's default (no --effort)

Env: MODEL (default claude-opus-4-7 — matches BU Bench's Claude bars), CLAUDE_BIN, MAX_TURNS (100).
Auth: loads CLAUDE_CODE_OAUTH_TOKEN from repo-root .env (or CLAUDE_KEY) from the repo-root .env.
Run in your own terminal (a nested claude from inside another Claude session can't auth).
"""
import base64, glob, json, os, shutil, signal, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]                      # repo root
RAW = HERE / os.environ.get("RAW_DIR", "raw"); RAW.mkdir(exist_ok=True)   # RAW_DIR override keeps a headed re-run separate from the headless baseline
SHOTS = Path(f"/tmp/shots-{os.getpid()}")   # per-process so parallel tasks never clobber each other's screenshots
# Headless per-run video via the bundled record_cdp.py CDP screencast recorder. On by default so
# the one expensive opus pass is captured once; set RECORD=0 to skip. Needs ffmpeg + websockets.
RECORDER = HERE / "record_cdp.py"
RECORD = os.environ.get("RECORD", "1") != "0"
# HEADED=1 runs a visible (non-headless) Chrome via `create --show`. Their Stealth Bench: local_headful
# ~50% vs local_headless ~3.8% anti-bot pass — headed defeats most headless fingerprinting (no proxy
# though, so pure IP blocks may persist). Baseline run is headless to match the local_headless tier.
HEADED = os.environ.get("HEADED", "0") == "1"
CLI = os.environ.get("BROWSER_CLI", "").split() or ["browser"]
RLOG = Path.home() / ".browser-daemon" / "requests.log"
MODEL = os.environ.get("MODEL", "claude-opus-4-7")
MAX_TURNS = os.environ.get("MAX_TURNS", "100")
TASK_TIMEOUT = int(os.environ.get("TASK_TIMEOUT", "1800"))  # per-task wall-clock cap (s); matches BU's claude_code_harness default (1800)


def load_token():
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return os.environ["CLAUDE_CODE_OAUTH_TOKEN"]
    envf = ROOT / ".env"
    if envf.exists():
        for key in ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_KEY"):
            for line in envf.read_text().splitlines():
                line = line.strip()
                if line.startswith(f"{key}=") or line.startswith(f"export {key}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def pick_claude():
    if os.environ.get("CLAUDE_BIN"):
        return os.environ["CLAUDE_BIN"]
    cand = sorted(glob.glob(str(Path.home() / "Library/Application Support/Claude/claude-code/*/claude.app/Contents/MacOS/claude")))
    for c in reversed(cand):
        if subprocess.run([c, "--help"], capture_output=True, text=True).stdout.find("--effort") >= 0:
            return c
    return "claude"


def run_cli(*args, sid=None):
    a = [*CLI] + ([sid] if sid else []) + list(args)
    return subprocess.run(a, capture_output=True, text=True).stdout


def steps_from_stream(objs):
    """Turn stream-json events into judge 'agent_steps' strings (assistant text + tool calls)."""
    steps = []
    for o in objs:
        if o.get("type") == "assistant":
            for b in (o.get("message", {}) or {}).get("content", []) or []:
                if b.get("type") == "text" and b.get("text", "").strip():
                    steps.append("assistant: " + b["text"].strip()[:500])
                elif b.get("type") == "tool_use":
                    inp = json.dumps(b.get("input", {}))[:200]
                    steps.append(f"tool {b.get('name')}: {inp}")
        elif o.get("type") == "user":
            for b in (o.get("message", {}) or {}).get("content", []) or []:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    c = b.get("content")
                    txt = c if isinstance(c, str) else json.dumps(c)[:300]
                    steps.append("result: " + (txt or "")[:300])
    return steps


def main():
    task_id = sys.argv[1]
    effort = sys.argv[2] if len(sys.argv) > 2 else None
    got = subprocess.run([sys.executable, str(HERE / "loader.py"), "get", task_id],
                         capture_output=True, text=True).stdout.strip()
    task = json.loads(got) if got else None
    if not task:
        print(f"task {task_id} not found"); sys.exit(1)

    if SHOTS.exists():
        shutil.rmtree(SHOTS)
    SHOTS.mkdir(parents=True, exist_ok=True)

    # PROFILE=<name> runs on a warmed persistent profile (inherits its trust cookies / logins);
    # otherwise an isolated ephemeral session. Robust sid extraction survives daemon-autostart noise.
    import re as _re
    PROFILE = os.environ.get("PROFILE", "")
    _base = ["create", "--profile", PROFILE] if PROFILE else ["create", "--ephemeral"]
    _out = run_cli(*_base, *(["--show"] if HEADED else []))
    _ids = _re.findall(r"\b[0-9a-f]{8}\b", _out)
    sid = _ids[-1] if _ids else _out.strip().split()[-1]

    # start headless video recording of THIS session's tab (tag the title so record_cdp can find it).
    rec_proc = None
    mp4_path = RAW / "video" / f"{task_id}.mp4"
    if RECORD and RECORDER.exists():
        mp4_path.parent.mkdir(parents=True, exist_ok=True)
        run_cli("eval", f"document.title='REC-{sid}'", sid=sid)
        rec_proc = subprocess.Popen([sys.executable, str(RECORDER), sid, str(mp4_path)],
                                    stderr=subprocess.DEVNULL)
        time.sleep(1.5)                     # let the recorder attach before the agent navigates

    t0 = time.time()
    prompt = (f"A browser session is ALREADY running and open for you. Its id is `{sid}`. Use ONLY "
              f"`browser {sid} <command>` for every browser action (see the system prompt for rules and the "
              f"command list). Save screenshots to {SHOTS}/step_<NNN>.png. End with a line "
              f"`FINAL ANSWER: <answer>`.\n\nTASK: {task['confirmed_task']}")

    claude = pick_claude(); tok = load_token()
    env = {**os.environ}
    if tok:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = tok
        # with a long-lived token, route to production: drop any staging/base-url vars from the CHILD
        # env (no-op in a normal terminal; lets this run from inside another Claude session too).
        for k in ("ANTHROPIC_BASE_URL", "USE_STAGING_OAUTH", "USE_LOCAL_OAUTH", "CLAUDE_CODE_OAUTH_SCOPES"):
            env.pop(k, None)
    else:
        print("WARNING: no CLAUDE_CODE_OAUTH_TOKEN/CLAUDE_KEY found in env or repo .env — claude may fail to auth", file=sys.stderr)
    # NOTE: NOT using --bare — it disables CLAUDE_CODE_OAUTH_TOKEN auth ("OAuth session expired").
    # (BU used --bare with a normally-logged-in claude; we depend on the token, so we can't.) The
    # /browser-cli skill therefore auto-loads; the hardened system_prompt.md forbids daemon/session
    # management to keep a generalist agent from spiraling into daemon debugging.
    cmd = [claude, "-p", prompt, "--model", MODEL, "--allowedTools", "Bash",
           "--dangerously-skip-permissions", "--output-format", "stream-json", "--verbose",
           "--max-turns", MAX_TURNS, "--append-system-prompt-file", str(HERE / "system_prompt.md")]
    # match BU's per-task API budget cap (their claude_code_harness default $10). MAX_BUDGET="" disables.
    _budget = os.environ.get("MAX_BUDGET", "10")
    if _budget:
        cmd += ["--max-budget-usd", _budget]
    if effort:
        cmd += ["--effort", effort]     # OMIT by default to match BU Bench (they set no effort)

    # Watchdog: if a browser session hangs, the agent retries browser commands that each time out at
    # ~2 min and can burn the full max-turns budget (observed a 33-min thrash). Cap total wall time so a
    # hung task fails fast and re-runs later instead of stalling the whole suite.
    stream_path = RAW / f"{task_id}.stream.txt"
    timed_out = False; proc_rc = None; proc_stderr = ""
    with stream_path.open("w") as f:
        try:
            _p = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, env=env, text=True, timeout=TASK_TIMEOUT)
            proc_rc = _p.returncode; proc_stderr = _p.stderr or ""
        except subprocess.TimeoutExpired as e:
            timed_out = True; proc_rc = -9
            st = getattr(e, "stderr", None) or b""
            proc_stderr = (st.decode(errors="replace") if isinstance(st, bytes) else str(st)) + f"\n[TASK_TIMEOUT after {TASK_TIMEOUT}s]"
    t1 = time.time()

    # finalize the video (SIGTERM -> record_cdp assembles frames into the mp4 via ffmpeg)
    video = None
    if rec_proc is not None:
        rec_proc.send_signal(signal.SIGTERM)
        try:
            rec_proc.wait(timeout=60)
        except Exception:
            rec_proc.kill()
        if mp4_path.exists() and mp4_path.stat().st_size > 0:
            video = str(mp4_path)

    objs = []
    for line in stream_path.read_text().splitlines():
        try:
            objs.append(json.loads(line))
        except Exception:
            pass
    result = next((o for o in reversed(objs) if o.get("type") == "result"), {})
    # Distinguish a genuine CRASH (transient: process died, auth blip, no result object, or claude's own
    # "error_during_execution") from a real task OUTCOME (completed, or hit max_turns = a legit fail we
    # should keep + judge). On a crash, do NOT write raw/<id>.json — otherwise resume would skip the
    # re-run and lock in a spurious FAIL. Persist an .error.json for debugging, clean up, exit nonzero
    # so run_suite logs the failure and a later resume re-runs this task fresh.
    # error_max_turns exits nonzero but IS a legit outcome (a real fail, like BU) -> keep + judge it.
    # Only a true crash (no result object at all, or claude's own error_during_execution) is dropped so
    # resume re-runs it. Do NOT gate on returncode: max_turns returns nonzero yet produced a result.
    crashed = timed_out or (not result) or result.get("subtype") == "error_during_execution"
    if crashed:
        (RAW / f"{task_id}.error.json").write_text(json.dumps({
            "task_id": task_id, "category": task.get("category"),
            "returncode": proc_rc, "subtype": result.get("subtype"), "timed_out": timed_out,
            "is_error": result.get("is_error"), "wall_s": round(t1 - t0, 1),
            "stderr_tail": (proc_stderr or "")[-3000:],
        }, indent=1))
        run_cli(sid, "delete")
        reason = "TIMEOUT" if timed_out else f"rc={proc_rc} subtype={result.get('subtype')!r}"
        print(f"[{task.get('category')}] {task_id}  CRASHED ({reason}) — bundle NOT written; will re-run on resume")
        sys.exit(1)
    text = result.get("result", "") or ""
    final_answer = ""
    for line in reversed(text.splitlines()):
        if line.strip().upper().startswith("FINAL ANSWER:"):
            final_answer = line.split(":", 1)[1].strip(); break
    # keep the FULL per-type usage breakdown (input/output/cache_read/cache_creation) so cost can be
    # computed later at any price point — the four types are priced very differently. agent_tokens is
    # just a convenience sum; don't reconstruct cost from it.
    usage = result.get("usage", {}) or {}
    agent_tokens = sum(usage.get(k, 0) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))

    reqs = []
    for line in (RLOG.read_text().splitlines() if RLOG.exists() else []):
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("t", 0) >= t0 and e.get("session") == sid:
            reqs.append(e)

    # persist screenshots per-task (SHOTS=/tmp/shots is wiped next run) so we can judge LATER, offline.
    # clear any stale shots from a prior partial attempt so a re-run doesn't mix step numbering.
    shot_dir = RAW / "shots" / task_id
    if shot_dir.exists():
        shutil.rmtree(shot_dir)
    shot_dir.mkdir(parents=True, exist_ok=True)
    shots = []
    for p in sorted(SHOTS.glob("*.png")):
        dst = shot_dir / p.name
        shutil.copyfile(p, dst)
        shots.append(str(dst))
    bundle = {
        "task_id": task_id, "category": task.get("category"), "confirmed_task": task["confirmed_task"],
        "ground_truth": task.get("answer"), "model": MODEL, "effort": effort or "(default)",
        "final_answer": final_answer, "agent_result_text": text, "agent_steps": steps_from_stream(objs),
        "screenshots": shots, "video": video, "stream_file": stream_path.name,
        "usage": usage, "agent_tokens": agent_tokens, "num_turns": result.get("num_turns"),
        "is_error": result.get("is_error"), "wall_s": round(t1 - t0, 1),
        "cli_calls": len(reqs), "cli_time_s": round(sum(e.get("dur", 0) for e in reqs), 2),
        "cost_usd": result.get("total_cost_usd"),   # CC's own figure; not surfaced upfront (compute from usage later)
    }
    # atomic write: a crash mid-write must never leave a partial raw/<id>.json that resume would
    # skip-and-judge. write to a temp file, then os.replace (atomic on the same filesystem).
    final = RAW / f"{task_id}.json"
    tmp = RAW / f".{task_id}.json.tmp"
    tmp.write_text(json.dumps(bundle, indent=1))
    os.replace(tmp, final)
    (RAW / f"{task_id}.error.json").unlink(missing_ok=True)   # clear any stale crash marker
    run_cli(sid, "delete")
    print(f"[{task.get('category')}] {task_id}  answer={final_answer!r}  cli_calls={len(reqs)}  shots={len(shots)}  video={'y' if video else 'n'}  tok={agent_tokens}  cost={bundle['cost_usd']}")


if __name__ == "__main__":
    main()
