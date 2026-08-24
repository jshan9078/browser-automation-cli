//! `browser` — thin client for browser-daemon. Speaks the same JSON-over-unix-socket protocol as
//! cli/main.py; exists to remove the ~25 ms Python start-up from every agent call.
use serde_json::{json, Map, Value};
use std::collections::{HashMap, HashSet};
use std::io::{Read, Write};
use std::os::unix::net::UnixStream;
use std::process::{exit, Command, Stdio};
use std::time::Duration;
use std::os::unix::net::UnixStream as StdUnixStream;

const HELP: &str = r##"browser — authenticated browser automation for coding agents

Standalone (no daemon):
  browser capture <url> [-f] [-o path]   Headless screenshot (viewport; -f full page)
  browser install [--all]                Download headless Chromium (~196 MB; --all adds the headed build,
                                         otherwise it is fetched automatically on first `show`)
  browser cleanup                        Kill Chromium processes started by this tool
  browser --version | update             Show version / upgrade (daily PyPI check; BROWSER_NO_UPDATE_CHECK=1 disables)
  browser docs [skill|agents]            Print the agent skill file / integration guide (shipped in the binary)

Daemon (auto-started on first use; run it yourself with `browser daemon`; BROWSER_NO_AUTOSTART=1 disables auto-start):
  browser create [--show]                New session (headless; --show opens a window, e.g. to log in)
  browser list [--table]                 Sessions as JSON (--table for humans)
  browser <id> show | hide               Move the session to a visible window / back to headless
  browser <id> delete                    Close session and forget its cookies
  browser shutdown                       Stop the daemon (sessions are saved and restored on next start)

Page commands (all print JSON; add -s/--snapshot to include a fresh snapshot in the result):
  browser <id> navigate <url> [--wait load|domcontentloaded|networkidle]
  browser <id> snapshot [scope-selector] [--all] [--max N] [--json]
                                         Interactive elements as "@e12 button "Create"" lines.
                                         --all adds text blocks; --json gives structured output
  browser <id> click <target> [--double]
  browser <id> type <target> <text> [--sequential] [--submit]   (alias: fill)
  browser <id> press <key> [target]      e.g. Enter, Tab, Control+a
  browser <id> hover <target>
  browser <id> select <target> <value>   <select> by value or label
  browser <id> scroll [up|down] [px]     or: scroll <target> to bring it into view
  browser <id> text [selector]           Readable text of the page or element
  browser <id> wait [--text T | --selector S] [--gone] [--timeout ms]
  browser <id> screenshot [target] [-o path] [-f] [-q quality]
  browser <id> eval <js-expression>
  browser <id> console [--clear]
  browser <id> back | forward
  browser <id> batch                     Read JSON lines from stdin, run them in order in one
                                         round-trip, stop at first failure. Each line is either
                                         {"cmd":"click @e3 -s"} or {"action":"text","params":{"selector":"#x"}}

Targets: @e12 (ref from snapshot, preferred) | CSS selector | text=Create | role=button[name=Create]
         | label=Widget name | placeholder=Search — or flags --text/--role/--name/--label/--placeholder.
Flags may appear anywhere after the session id.
"##;

fn socket_path() -> std::path::PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".into());
    std::path::Path::new(&home).join(".browser-daemon").join("socket")
}

fn send_request(req: &Value) -> Value {
    let path = socket_path();
    let mut last_err = String::new();
    for attempt in 0..5 {
        match UnixStream::connect(&path) {
            Ok(mut s) => {
                let _ = s.set_read_timeout(Some(Duration::from_secs(600)));
                if let Err(e) = s.write_all(req.to_string().as_bytes()) { return err_json(&e.to_string()); }
                let _ = s.shutdown(std::net::Shutdown::Write);
                let mut buf = Vec::new();
                if let Err(e) = s.read_to_end(&mut buf) { return err_json(&e.to_string()); }
                return serde_json::from_slice(&buf).unwrap_or_else(|e| err_json(&format!("bad response: {e}")));
            }
            Err(e) => {
                last_err = match e.kind() {
                    std::io::ErrorKind::NotFound | std::io::ErrorKind::ConnectionRefused => {
                        // no daemon: start one ourselves, once, unless disabled or shutting down
                        use std::sync::atomic::Ordering;
                        if AUTOSTART.swap(false, Ordering::SeqCst) && std::env::var("BROWSER_NO_AUTOSTART").is_err() {
                            eprintln!("Starting browser-daemon (auto; BROWSER_NO_AUTOSTART=1 to disable)...");
                            match autospawn_daemon() { Ok(()) => continue, Err(e2) => e2 }
                        } else if e.kind() == std::io::ErrorKind::NotFound { "Daemon not running. Start with: browser daemon &".into() } else { "Connection refused. Is another daemon running?".into() }
                    }
                    _ => e.to_string(),
                };
                if attempt < 4 { std::thread::sleep(Duration::from_millis(100)); }
            }
        }
    }
    err_json(&last_err)
}

fn err_json(msg: &str) -> Value { json!({"success": false, "error": msg}) }

/// Split positional args from flags. Boolean flags take no value; valued flags take the next arg.
fn parse_flags(args: &[String], bools: &[&str], valued: &[&str]) -> (Vec<String>, HashMap<String, Value>) {
    let bools: HashSet<&str> = bools.iter().copied().collect();
    let valued: HashSet<&str> = valued.iter().copied().collect();
    let mut pos = Vec::new();
    let mut flags = HashMap::new();
    let mut i = 0;
    while i < args.len() {
        let a = args[i].as_str();
        if bools.contains(a) {
            flags.insert(a.trim_start_matches('-').to_string(), Value::Bool(true));
        } else if valued.contains(a) && i + 1 < args.len() {
            flags.insert(a.trim_start_matches('-').to_string(), Value::String(args[i + 1].clone()));
            i += 1;
        } else if let Some(rest) = a.strip_prefix("--").filter(|r| r.contains('=')) {
            let (k, v) = rest.split_once('=').unwrap();
            flags.insert(k.to_string(), Value::String(v.to_string()));
        } else {
            pos.push(a.to_string());
        }
        i += 1;
    }
    (pos, flags)
}

const BOOLS: &[&str] = &["-s", "--snapshot", "--all", "--json", "--double", "--sequential", "--submit", "--gone", "-f", "--full-page", "--clear", "--table"];
const VALUED: &[&str] = &["--text", "--role", "--name", "--label", "--placeholder", "--wait", "--max", "--timeout", "-o", "--output", "-q", "--quality", "--selector", "--format"];

fn target_params(f: &HashMap<String, Value>) -> Map<String, Value> {
    let mut p = Map::new();
    for k in ["text", "role", "name", "label", "placeholder"] {
        if let Some(v) = f.get(k) { p.insert(k.into(), v.clone()); }
    }
    if f.contains_key("s") || f.contains_key("snapshot") { p.insert("snap".into(), Value::Bool(true)); }
    p
}

fn has_target_flags(tp: &Map<String, Value>) -> bool { tp.keys().any(|k| k != "snap") }

fn num(v: &Value) -> Option<f64> { v.as_str().and_then(|s| s.parse().ok()) }

/// Translate CLI words into one daemon request. None for unknown actions / missing args.
fn build(sid: &str, action: &str, rest: &[String]) -> Option<Value> {
    let (pos, f) = parse_flags(rest, BOOLS, VALUED);
    let tp = target_params(&f);
    let req = |a: &str, p: Map<String, Value>| Some(json!({"action": a, "session_id": sid, "params": p}));
    let sel = |i: usize| pos.get(i).cloned().unwrap_or_default();
    let mut p = tp.clone();
    match action {
        "navigate" if !pos.is_empty() => {
            p.insert("url".into(), json!(pos[0]));
            if let Some(w) = f.get("wait") { p.insert("wait".into(), w.clone()); }
            if let Some(t) = f.get("timeout").and_then(num) { p.insert("timeout".into(), json!(t)); }
            req("navigate", p)
        }
        "snapshot" => {
            let mut p = Map::new();
            if let Some(s) = pos.first() { p.insert("selector".into(), json!(s)); }
            if f.contains_key("all") { p.insert("all".into(), json!(true)); }
            if let Some(m) = f.get("max").and_then(num) { p.insert("max".into(), json!(m as i64)); }
            if f.contains_key("json") || f.get("format").and_then(|v| v.as_str()) == Some("json") { p.insert("format".into(), json!("json")); }
            req("snapshot", p)
        }
        "click" => {
            p.insert("selector".into(), json!(sel(0)));
            if f.contains_key("double") { p.insert("double".into(), json!(true)); }
            req("click", p)
        }
        "type" | "fill" => {
            let (s, t) = if has_target_flags(&tp) { (String::new(), sel(0)) } else if pos.len() >= 2 { (pos[0].clone(), pos[1].clone()) } else { return None };
            p.insert("selector".into(), json!(s));
            p.insert("text_value".into(), json!(t));
            if f.contains_key("sequential") { p.insert("sequential".into(), json!(true)); }
            if f.contains_key("submit") { p.insert("submit".into(), json!(true)); }
            req("type", p)
        }
        "press" if !pos.is_empty() => {
            p.insert("key".into(), json!(pos[0]));
            p.insert("selector".into(), json!(sel(1)));
            req("press_key", p)
        }
        "hover" => { p.insert("selector".into(), json!(sel(0))); req("hover", p) }
        "select" => {
            let (s, v) = if has_target_flags(&tp) && !pos.is_empty() { (String::new(), pos[0].clone()) } else if pos.len() >= 2 { (pos[0].clone(), pos[1].clone()) } else { return None };
            p.insert("selector".into(), json!(s));
            p.insert("value".into(), json!(v));
            req("select_option", p)
        }
        "scroll" => {
            for a in &pos {
                if a == "up" || a == "down" { p.insert("direction".into(), json!(a)); }
                else if a.trim_start_matches('-').chars().all(|c| c.is_ascii_digit()) && !a.is_empty() { p.insert("amount".into(), json!(a.parse::<i64>().unwrap_or(0))); }
                else { p.insert("selector".into(), json!(a)); }
            }
            req("scroll", p)
        }
        "text" => {
            let mut p = Map::new();
            if let Some(s) = pos.first() { p.insert("selector".into(), json!(s)); }
            if let Some(m) = f.get("max").and_then(num) { p.insert("max".into(), json!(m as i64)); }
            req("text", p)
        }
        "wait" => {
            let mut p = Map::new();
            if let Some(t) = f.get("text") { p.insert("text".into(), t.clone()); }
            if let Some(s) = f.get("selector") { p.insert("selector".into(), s.clone()); }
            else if let Some(s) = pos.first() { p.insert("selector".into(), json!(s)); }
            if f.contains_key("gone") { p.insert("gone".into(), json!(true)); }
            if let Some(t) = f.get("timeout").and_then(num) { p.insert("timeout".into(), json!(t)); }
            req("wait", p)
        }
        "screenshot" => {
            let mut p: Map<String, Value> = tp.iter().filter(|(k, _)| k.as_str() != "snap").map(|(k, v)| (k.clone(), v.clone())).collect();
            if let Some(s) = pos.first() { p.insert("selector".into(), json!(s)); }
            if let Some(o) = f.get("o").or(f.get("output")) { p.insert("output".into(), o.clone()); }
            if f.contains_key("f") || f.contains_key("full-page") { p.insert("full_page".into(), json!(true)); }
            if let Some(q) = f.get("q").or(f.get("quality")).and_then(num) { p.insert("quality".into(), json!(q as i64)); }
            req("screenshot", p)
        }
        "eval" if !pos.is_empty() => { let mut p = Map::new(); p.insert("expression".into(), json!(pos.join(" "))); req("eval", p) }
        "console" => { let mut p = Map::new(); p.insert("clear".into(), json!(f.contains_key("clear"))); req("console_logs", p) }
        "back" => req("go_back", tp),
        "forward" => req("go_forward", tp),
        "show" | "hide" | "delete" => Some(json!({"action": action, "session_id": sid})),
        _ => None,
    }
}

/// Print results compactly: snapshot text as-is when it is the only payload, else JSON (+ snapshot).
fn output(mut result: Value) -> i32 {
    let snap = result.as_object_mut().and_then(|o| o.remove("snapshot"));
    let ok = result.get("success").and_then(|v| v.as_bool()).unwrap_or(true);
    let plain_keys = ["success", "url", "title", "settled", "warning"];
    let only_plain = result.as_object().map(|o| o.keys().all(|k| plain_keys.contains(&k.as_str()))).unwrap_or(false);
    match (&snap, ok && only_plain) {
        (Some(Value::String(s)), true) => println!("{s}"),
        _ => {
            println!("{}", serde_json::to_string_pretty(&result).unwrap());
            if let Some(Value::String(s)) = snap { println!("{s}"); }
        }
    }
    if ok { 0 } else { 1 }
}

/// Kill Chromium processes launched from Playwright's cache (ours), nothing else.
fn cleanup() -> i32 {
    let out = Command::new("ps").args(["-Ao", "pid,command"]).output().map(|o| String::from_utf8_lossy(&o.stdout).to_string()).unwrap_or_default();
    let mut n = 0;
    for line in out.lines().skip(1) {
        let line = line.trim_start();
        let (pid, cmd) = match line.split_once(' ') { Some(x) => x, None => continue };
        if cmd.contains("ms-playwright") && cmd.to_lowercase().contains("chrom") {
            if let Ok(p) = pid.parse::<i32>() { if Command::new("kill").arg(p.to_string()).status().map(|s| s.success()).unwrap_or(false) { n += 1; } }
        }
    }
    println!("{}", if n > 0 { format!("Killed {n} Chromium process(es)") } else { "No Playwright Chromium processes found".into() });
    0
}

#[allow(dead_code)]
fn python_fallback(args: &[String]) -> ! {
    // capture/install need Playwright; delegate to the Python CLI if it is installed.
    let candidates = ["browser-py", "python3"];
    for c in candidates {
        let mut cmd = Command::new(c);
        if c == "python3" { cmd.arg("-m").arg("cli.main"); }
        cmd.args(args).stdin(Stdio::inherit()).stdout(Stdio::inherit()).stderr(Stdio::inherit());
        if let Ok(st) = cmd.status() { exit(st.code().unwrap_or(1)); }
    }
    eprintln!("{{\"success\": false, \"error\": \"`{}` needs the Python package (uv tool install browser-automation-cli)\"}}", args[0]);
    exit(1);
}

fn batch(sid: &str) -> i32 {
    let mut input = String::new();
    std::io::stdin().read_to_string(&mut input).ok();
    let mut reqs = Vec::new();
    for line in input.lines().map(str::trim).filter(|l| !l.is_empty()) {
        let v: Value = match serde_json::from_str(line) { Ok(v) => v, Err(e) => { println!("{}", err_json(&format!("bad batch line: {e}"))); return 1; } };
        if let Some(cmd) = v.get("cmd").and_then(|c| c.as_str()) {
            let words: Vec<String> = shell_words(cmd);
            if words.is_empty() { continue; }
            reqs.push(build(sid, &words[0], &words[1..]).unwrap_or(json!({"action": "unknown"})));
        } else {
            let mut v = v;
            if v.get("session_id").is_none() { v["session_id"] = json!(sid); }
            reqs.push(v);
        }
    }
    let result = send_request(&json!({"action": "batch", "requests": reqs}));
    println!("{}", serde_json::to_string_pretty(&result).unwrap());
    let ok = result.get("success").and_then(|v| v.as_bool()).unwrap_or(false)
        && result.get("results").and_then(|r| r.as_array()).map(|a| a.iter().all(|r| r.get("success").and_then(|v| v.as_bool()).unwrap_or(false))).unwrap_or(false);
    if ok { 0 } else { 1 }
}

/// Minimal shell-like splitting with single/double quotes (for {"cmd": ...} batch lines).
fn shell_words(s: &str) -> Vec<String> {
    let mut out = Vec::new(); let mut cur = String::new(); let mut q: Option<char> = None; let mut had = false;
    for c in s.chars() {
        match (q, c) {
            (Some(x), c) if c == x => q = None,
            (None, '"') | (None, '\'') => { q = Some(c); had = true; }
            (None, c) if c.is_whitespace() => { if had || !cur.is_empty() { out.push(std::mem::take(&mut cur)); had = false; } }
            (_, c) => cur.push(c),
        }
    }
    if had || !cur.is_empty() { out.push(cur); }
    out
}

fn update_notice() { browser_cli::update::notice(); }

/// Standalone screenshot without the daemon: launch headless Chromium, navigate, capture.
fn capture(args: &[String]) -> i32 {
    let (pos, f) = parse_flags(args, &["-f", "--full-page"], &["-o", "--output"]);
    let Some(url) = pos.first().cloned() else { eprintln!("usage: browser capture <url> [-f] [-o path]"); return 2 };
    let full = f.contains_key("f") || f.contains_key("full-page");
    let out = f.get("o").or(f.get("output")).and_then(|v| v.as_str()).map(String::from);
    let rt = tokio::runtime::Builder::new_multi_thread().enable_all().build().unwrap();
    let r = rt.block_on(async move {
        let mut b = browser_cli::chrome::launch(true).await?;
        let cdp = b.cdp.clone();
        let t = cdp.send(None, "Target.createTarget", json!({"url": "about:blank"})).await?;
        let a = cdp.send(None, "Target.attachToTarget", json!({"targetId": t["targetId"], "flatten": true})).await?;
        let page = browser_cli::actions::Page { cdp: cdp.clone(), sid: a["sessionId"].as_str().unwrap_or("").to_string(), inflight: std::sync::Arc::new(std::sync::atomic::AtomicI64::new(0)) };
        page.send("Page.enable", json!({})).await?;
        page.send("Emulation.setDeviceMetricsOverride", json!({"width": 1280, "height": 800, "deviceScaleFactor": 1, "mobile": false})).await?;
        page.send("Page.navigate", json!({"url": url})).await?;
        let _ = page.wait_ready("complete", 30_000).await;
        tokio::time::sleep(std::time::Duration::from_millis(300)).await;
        let mut p = Map::new();
        if full { p.insert("full_page".into(), json!(true)); }
        let path = out.unwrap_or_else(|| format!("/tmp/browser_capture_{}.jpg", std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)));
        p.insert("output".into(), json!(path));
        let r = browser_cli::actions::screenshot(&page, &p, "capture").await;
        b.close().await;
        Ok::<Value, String>(r)
    });
    match r { Ok(mut v) => { if v.get("success").and_then(|x| x.as_bool()).unwrap_or(false) { v["full_page"] = json!(full); } output(v) } Err(e) => { println!("{}", err_json(&e)); 1 } }
}

fn update_cmd() -> i32 {
    let info = browser_cli::update::check_now();
    let Some(latest) = info["latest"].as_str() else { eprintln!("Could not reach PyPI: {}", info["error"]); return 1 };
    if browser_cli::update::is_newer(latest, browser_cli::update::CURRENT) {
        println!("{latest} available (you have {}). Upgrading with: uv tool upgrade browser-automation-cli", browser_cli::update::CURRENT);
        let st = Command::new("uv").args(["tool", "upgrade", "browser-automation-cli"]).status();
        match st { Ok(s) if s.success() => { println!("Restart the daemon to use the new version: browser shutdown && browser-daemon &"); 0 } _ => { eprintln!("Upgrade failed; run it manually: uv tool upgrade browser-automation-cli (or pip install -U browser-automation-cli)"); 1 } }
    } else { println!("Up to date ({}).", browser_cli::update::CURRENT); 0 }
}

/// Start the daemon detached, logging to ~/.browser-daemon/daemon.log, and wait for the socket.
fn autospawn_daemon() -> Result<(), String> {
    let dir = socket_path().parent().unwrap().to_path_buf();
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let log = std::fs::OpenOptions::new().create(true).append(true).open(dir.join("daemon.log")).map_err(|e| e.to_string())?;
    let me = std::env::current_exe().map_err(|e| e.to_string())?;
    std::process::Command::new(me).arg("daemon").arg("--auto")
        .stdin(Stdio::null()).stdout(Stdio::null()).stderr(log)
        .spawn().map_err(|e| format!("could not start the daemon: {e}"))?;
    for _ in 0..150 {
        if StdUnixStream::connect(socket_path()).is_ok() { return Ok(()); }
        std::thread::sleep(Duration::from_millis(100));
    }
    Err("daemon did not come up within 15s; see ~/.browser-daemon/daemon.log".into())
}

static AUTOSTART: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(true);

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() || args[0] == "-h" || args[0] == "--help" { print!("{HELP}"); update_notice(); return; }
    if args[0] == "--version" || args[0] == "-V" || args[0] == "version" { let c = browser_cli::update::read_cache(); println!("{}", json!({"version": env!("CARGO_PKG_VERSION"), "client": "rust", "latest": browser_cli::update::cached_latest(), "checked_at": c["checked_at"]})); update_notice(); return; }
    let cmd = args[0].as_str();
    if cmd == "daemon" {
        let rt = tokio::runtime::Builder::new_multi_thread().enable_all().build().expect("tokio runtime");
        if let Err(e) = rt.block_on(browser_cli::server::run()) { eprintln!("[daemon] fatal: {e}"); exit(1); }
        return;
    }
    if cmd == "shutdown" { AUTOSTART.store(false, std::sync::atomic::Ordering::SeqCst); }
    let code = match cmd {
        "capture" => capture(&args[1..]),
        "install" => match browser_cli::install::run(&args[1..]) { Ok(()) => 0, Err(e) => { eprintln!("{}", err_json(&e)); 1 } },
        "update" => update_cmd(),
        "docs" => {
            // shipped with the binary so an installed tool is self-documenting for agents
            match args.get(1).map(String::as_str) {
                Some("agents") => print!("{}", include_str!("../AGENTS.md")),
                _ => print!("{}", include_str!("../SKILL.md")),
            }
            0
        }
        "cleanup" => cleanup(),
        "create" => {
            let visible = args[1..].iter().any(|a| matches!(a.as_str(), "--show" | "--visible" | "--headed"));
            let r = send_request(&json!({"action": "create", "params": {"visible": visible}}));
            if r.get("success").and_then(|v| v.as_bool()).unwrap_or(false) { println!("{}", r["session_id"].as_str().unwrap_or("")); 0 }
            else { eprintln!("Error: {}", r.get("error").and_then(|e| e.as_str()).unwrap_or("unknown")); 1 }
        }
        "list" => {
            let r = send_request(&json!({"action": "list"}));
            if !r.get("success").and_then(|v| v.as_bool()).unwrap_or(false) { eprintln!("Error: {}", r.get("error").and_then(|e| e.as_str()).unwrap_or("unknown")); 1 }
            else if args.iter().any(|a| a == "--table") {
                println!("{:<10} {:<11} {:<4} {:<50} TITLE", "SESSION_ID", "STATE", "VIS", "URL");
                for s in r["sessions"].as_array().cloned().unwrap_or_default() {
                    let g = |k: &str| s.get(k).and_then(|v| v.as_str()).unwrap_or("").to_string();
                    let url: String = g("url").chars().take(48).collect(); let title: String = g("title").chars().take(30).collect();
                    println!("{:<10} {:<11} {:<4} {:<50} {}", g("session_id"), g("state"), if s["visible"].as_bool().unwrap_or(false) { "yes" } else { "no" }, url, title);
                }
                0
            } else { println!("{}", serde_json::to_string_pretty(&r["sessions"]).unwrap()); 0 }
        }
        "shutdown" => output(send_request(&json!({"action": "shutdown"}))),
        "delete" if args.len() >= 2 => output(send_request(&json!({"action": "delete", "session_id": args[1]}))),
        _ if args.len() >= 2 => {
            let sid = &args[0];
            // flags may appear anywhere: the action is the first non-flag word after the session id
            let mut rest: Vec<String> = args[1..].to_vec();
            let idx = rest.iter().position(|a| !a.starts_with('-')).unwrap_or(0);
            let action = rest.remove(idx);
            if action == "batch" { batch(sid) }
            else {
                match build(sid, &action, &rest) {
                    Some(req) => output(send_request(&req)),
                    None => { eprintln!("Unknown action or missing args: {action}\n\n{HELP}"); 2 }
                }
            }
        }
        _ => { eprint!("{HELP}"); 2 }
    };
    update_notice();
    exit(code);
}
