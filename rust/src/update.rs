//! Daily PyPI check (daemon side) -> ~/.browser-daemon/update.json; the CLI only reads that file.
use serde_json::{json, Value};
use std::path::PathBuf;

pub const PACKAGE: &str = "browser-automation-cli";
pub const CURRENT: &str = env!("CARGO_PKG_VERSION");

pub fn cache_path() -> PathBuf { PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".browser-daemon").join("update.json") }

pub fn key(v: &str) -> Vec<u64> { v.split(|c| c == '.' || c == '-').map(|x| x.parse::<u64>().unwrap_or(0)).collect() }
fn norm(v: &str) -> String { v.replace("-alpha.", "a").replace("-beta.", "b").replace("-rc.", "rc") }
/// PEP 440-ish: "0.4.0a1" < "0.4.0"; "0.4.0-alpha.1" is the cargo spelling of the same.
pub fn is_newer(latest: &str, current: &str) -> bool {
    let (l, c) = (norm(latest), norm(current));
    let strip = |s: &str| -> (Vec<u64>, bool) { let pre = s.contains('a') || s.contains('b') || s.contains("rc"); let base: String = s.chars().take_while(|ch| ch.is_ascii_digit() || *ch == '.').collect(); (key(&base), pre) };
    let (lk, lpre) = strip(&l); let (ck, cpre) = strip(&c);
    if lk != ck { return lk > ck; }
    !lpre && cpre
}

pub fn fetch_latest() -> Result<String, String> {
    let r = ureq::get(&format!("https://pypi.org/pypi/{PACKAGE}/json")).timeout(std::time::Duration::from_secs(5)).call().map_err(|e| e.to_string())?;
    let v: Value = serde_json::from_str(&r.into_string().map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
    v["info"]["version"].as_str().map(String::from).ok_or("no version in PyPI response".into())
}

pub fn check_now() -> Value {
    let mut info = json!({"checked_at": std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0), "current": CURRENT, "client": "rust"});
    match fetch_latest() { Ok(l) => info["latest"] = json!(l), Err(e) => info["error"] = json!(e) }
    let p = cache_path();
    if let Some(d) = p.parent() { let _ = std::fs::create_dir_all(d); }
    let _ = std::fs::write(&p, info.to_string());
    info
}

pub fn read_cache() -> Value { std::fs::read_to_string(cache_path()).ok().and_then(|t| serde_json::from_str(&t).ok()).unwrap_or(Value::Null) }

/// One-line stderr hint when the cache shows a newer release. Silent if opted out / unknown.
pub fn notice() {
    if std::env::var("BROWSER_NO_UPDATE_CHECK").is_ok() { return; }
    let c = read_cache();
    if let Some(latest) = c["latest"].as_str() {
        if is_newer(latest, CURRENT) {
            eprintln!("{PACKAGE} {latest} is available (you have {CURRENT}): uv tool upgrade {PACKAGE}  (BROWSER_NO_UPDATE_CHECK=1 to silence)");
        }
    }
}

/// Daemon side: check if the cache is older than a day, then daily.
pub fn start_background_checks() {
    if std::env::var("BROWSER_NO_UPDATE_CHECK").is_ok() { return; }
    std::thread::spawn(|| loop {
        let c = read_cache();
        let age = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0) - c["checked_at"].as_f64().unwrap_or(0.0);
        if age > 86400.0 { let i = check_now(); if let Some(l) = i["latest"].as_str() { if is_newer(l, CURRENT) { eprintln!("[daemon] update available: {PACKAGE} {l} (running {CURRENT})"); } } }
        std::thread::sleep(std::time::Duration::from_secs(3600));
    });
}
