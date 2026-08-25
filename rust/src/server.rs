//! Unix-socket JSON server: identical protocol to the Python daemon (request = one JSON object,
//! EOF terminated; response = one JSON object). Also writes ~/.browser-daemon/requests.log.
use crate::actions::{self, Page};
use crate::session::{Manager, Shared};
use serde_json::{json, Map, Value};
use std::path::PathBuf;
use std::sync::Arc;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::UnixListener;
use tokio::sync::Mutex;

pub fn base_dir() -> PathBuf { PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".browser-daemon") }
pub fn socket_path() -> PathBuf { base_dir().join("socket") }

async fn dispatch(page: &Page, session_id: &str, action: &str, params: &Map<String, Value>, shared: &Shared) -> Value {
    match action {
        "navigate" => actions::navigate(page, params).await,
        "snapshot" => actions::snapshot_p(page, params).await,
        "click" => actions::click(page, params).await,
        "type" => actions::type_text(page, params).await,
        "hover" => actions::hover(page, params).await,
        "select_option" => actions::select_option(page, params).await,
        "press_key" => actions::press_key(page, params).await,
        "scroll" => actions::scroll(page, params).await,
        "text" => actions::get_text(page, params).await,
        "eval" => actions::evaluate(page, params).await,
        "wait" => actions::wait_for(page, params).await,
        "screenshot" => actions::screenshot(page, params, session_id).await,
        "console_logs" => {
            let mut m = shared.lock().await;
            let s = m.sessions.get_mut(session_id).unwrap();
            let logs: Vec<Value> = s.console.iter().cloned().collect();
            if params.get("clear").and_then(|v| v.as_bool()).unwrap_or(false) { s.console.clear(); }
            json!({"success": true, "logs": logs})
        }
        "go_back" => actions::history(page, params, -1).await,
        "go_forward" => actions::history(page, params, 1).await,
        _ => json!({"success": false, "error": format!("Unknown action: {action}")}),
    }
}

pub async fn process(shared: &Shared, request: &Value, shutdown: &tokio::sync::watch::Sender<bool>) -> Value {
    let action = request.get("action").and_then(|v| v.as_str()).unwrap_or("");
    let session_id = request.get("session_id").and_then(|v| v.as_str()).map(String::from);
    let mut params: Map<String, Value> = request.get("params").and_then(|v| v.as_object()).cloned().unwrap_or_default();
    // legacy clients (<= 0.2) send `type {selector, text}`; `text` is a targeting flag in the new protocol
    if action == "type" && !params.contains_key("text_value") && params.get("selector").and_then(|v| v.as_str()).map(|s| !s.is_empty()).unwrap_or(false) {
        if let Some(t) = params.remove("text") { params.insert("text_value".into(), t); }
    }
    match action {
        "create" => {
            let visible = params.get("visible").and_then(|v| v.as_bool()).unwrap_or(false);
            // per-session profile: explicit --ephemeral / --profile <name>, else the daemon default
            let profile = if params.get("ephemeral").and_then(|v| v.as_bool()).unwrap_or(false) { None }
                else if let Some(p) = params.get("profile").and_then(|v| v.as_str()).filter(|s| !s.is_empty()) { Some(p.to_string()) }
                else { crate::chrome::config_profile() };
            let mut m = shared.lock().await;
            match m.create(profile.clone(), visible).await {
                Ok(id) => json!({"success": true, "session_id": id, "visible": visible, "profile": profile.unwrap_or_else(|| "ephemeral".into())}),
                Err(e) => json!({"success": false, "error": e}),
            }
        }
        "list" => json!({"success": true, "sessions": shared.lock().await.list()}),
        "shutdown" => { let _ = shutdown.send(true); json!({"success": true}) }
        _ => {
            let Some(sid) = session_id else { return json!({"success": false, "error": "session_id required for this action"}) };
            match action {
                "delete" => { let ok = shared.lock().await.delete(&sid).await; json!({"success": ok, "error": if ok { Value::Null } else { json!("Session not found") }}) }
                "show" | "hide" => match shared.lock().await.set_visible(&sid, action == "show").await { Ok(()) => json!({"success": true, "error": null}), Err(e) => json!({"success": false, "error": e}) },
                _ => {
                    let page = match shared.lock().await.wake(&sid).await { Ok(p) => p, Err(e) => return json!({"success": false, "error": e}) };
                    // the manager lock is NOT held while the action runs, so other sessions proceed in parallel
                    let result = dispatch(&page, &sid, action, &params, shared).await;
                    let title = page.title().await;
                    let mut m = shared.lock().await;
                    if let Some(s) = m.sessions.get_mut(&sid) { s.title = title; }
                    m.done(&sid);
                    result
                }
            }
        }
    }
}

fn log_request(request: &Value, response: &Value, dur: f64, nbytes: usize) {
    let sub = if request["action"] == "batch" { request.get("requests").and_then(|r| r.as_array()) } else { None };
    let entry = json!({
        "t": (std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0) * 1000.0).round() / 1000.0,
        "dur": (dur * 10000.0).round() / 10000.0,
        "session": request.get("session_id").cloned().or_else(|| sub.and_then(|s| s.first()).and_then(|r| r.get("session_id")).cloned()).unwrap_or(Value::Null),
        "action": request.get("action"), "params": request.get("params"),
        "batch": sub.map(|s| s.iter().map(|r| r.get("action").cloned().unwrap_or(Value::Null)).collect::<Vec<_>>()),
        "ok": response.get("success").and_then(|v| v.as_bool()).unwrap_or(false), "bytes": nbytes,
    });
    let p = base_dir().join("requests.log");
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(&p) { use std::io::Write; let _ = writeln!(f, "{entry}"); }
    actions::set_mode(&p, 0o600);
}

pub async fn run() -> Result<(), String> {
    let base = base_dir();
    std::fs::create_dir_all(&base).map_err(|e| e.to_string())?; actions::set_mode(&base, 0o700);
    let sock = socket_path();
    // If a daemon already serves this socket, exit quietly: with client auto-spawn, two concurrent
    // first-commands may both try to start one; the loser must not clobber the winner's socket.
    if std::os::unix::net::UnixStream::connect(&sock).is_ok() {
        eprintln!("[daemon] already running at {}", sock.display());
        return Ok(());
    }
    let _ = std::fs::remove_file(&sock);
    crate::update::start_background_checks();
    let shared: Shared = Arc::new(Mutex::new(Manager::new()));
    // browsers are launched per session on demand (one process per distinct profile in use)
    match crate::chrome::config_profile() {
        Some(p) => eprintln!("[daemon] default profile: {p}"),
        None => eprintln!("[daemon] default: ephemeral sessions"),
    }
    let listener = UnixListener::bind(&sock).map_err(|e| format!("bind {}: {e}", sock.display()))?;
    actions::set_mode(&sock, 0o600);
    let sock_ino = std::fs::metadata(&sock).ok().map(|m| { use std::os::unix::fs::MetadataExt; m.ino() });
    eprintln!("[daemon] ready, socket at {}", sock.display());

    let (shutdown_tx, mut shutdown_rx) = tokio::sync::watch::channel(false);
    // console events -> session buffers
    {
        let shared = shared.clone();
        tokio::spawn(async move {
            loop {
                let cdps: Vec<crate::cdp::Cdp> = { let m = shared.lock().await; m.browsers.values().map(|b| b.cdp.clone()).collect() };
                let mut rxs: Vec<_> = cdps.iter().map(|c| c.subscribe()).collect();
                if rxs.is_empty() { tokio::time::sleep(std::time::Duration::from_secs(1)).await; continue; }
                let deadline = tokio::time::sleep(std::time::Duration::from_secs(5));
                tokio::pin!(deadline);
                loop {
                    tokio::select! {
                        _ = &mut deadline => break, // re-subscribe periodically in case browsers changed
                        ev = rxs[0].recv() => match ev {
                            Ok(ev) if ev.method == "Runtime.consoleAPICalled" => {
                                let text = ev.params["args"].as_array().map(|a| a.iter().map(|x| x.get("value").map(|v| if v.is_string() { v.as_str().unwrap().to_string() } else { v.to_string() }).or_else(|| x.get("description").and_then(|d| d.as_str()).map(String::from)).unwrap_or_default()).collect::<Vec<_>>().join(" ")).unwrap_or_default();
                                if let Some(sid) = &ev.session_id { shared.lock().await.push_console(sid, json!({"type": ev.params["type"], "text": text, "t": std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0)})); }
                            }
                            Ok(_) => {}
                            Err(_) => break,
                        }
                    }
                }
            }
        });
    }
    // housekeeper
    { let shared = shared.clone(); tokio::spawn(async move { loop { tokio::time::sleep(crate::session::idle_sleep()).await; shared.lock().await.housekeep().await; } }); }
    // signals
    { let tx = shutdown_tx.clone(); tokio::spawn(async move {
        let mut term = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()).unwrap();
        tokio::select! { _ = tokio::signal::ctrl_c() => {}, _ = term.recv() => {} }
        let _ = tx.send(true);
    }); }

    loop {
        tokio::select! {
            _ = shutdown_rx.changed() => { if *shutdown_rx.borrow() { break; } }
            acc = listener.accept() => {
                let Ok((stream, _)) = acc else { continue };
                let shared = shared.clone(); let tx = shutdown_tx.clone();
                tokio::spawn(async move {
                    let (mut rd, mut wr) = stream.into_split();
                    let mut buf = Vec::new();
                    if rd.read_to_end(&mut buf).await.is_err() || buf.is_empty() { return; }
                    let request: Value = match serde_json::from_slice(&buf) { Ok(v) => v, Err(e) => { let _ = wr.write_all(json!({"success": false, "error": format!("bad request: {e}")}).to_string().as_bytes()).await; return; } };
                    let t0 = std::time::Instant::now();
                    let response = if request["action"] == "batch" {
                        let mut results = Vec::new();
                        for r in request.get("requests").and_then(|r| r.as_array()).cloned().unwrap_or_default() {
                            let res = process(&shared, &r, &tx).await;
                            let ok = res.get("success").and_then(|v| v.as_bool()).unwrap_or(false);
                            results.push(res);
                            if !ok { break; }
                        }
                        json!({"success": true, "results": results})
                    } else { process(&shared, &request, &tx).await };
                    let payload = response.to_string();
                    let _ = wr.write_all(payload.as_bytes()).await;
                    let _ = wr.shutdown().await;
                    log_request(&request, &response, t0.elapsed().as_secs_f64(), payload.len());
                });
            }
        }
    }
    eprintln!("[daemon] stopping...");
    shared.lock().await.close_all().await;
    if let Some(ino) = sock_ino { if std::fs::metadata(&sock).ok().map(|m| { use std::os::unix::fs::MetadataExt; m.ino() }) == Some(ino) { let _ = std::fs::remove_file(&sock); } }
    eprintln!("[daemon] stopped");
    Ok(())
}
