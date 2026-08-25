//! Locate and launch Chromium (Playwright's cached builds, or an explicit path), return a CDP client.
use crate::cdp::Cdp;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};

pub const LAUNCH_ARGS: &[&str] = &[
    "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled", "--disable-gpu",
    "--force-prefers-reduced-motion", "--disable-background-networking", "--disable-component-update",
    "--no-first-run", "--no-default-browser-check", "--disable-sync", "--disable-extensions",
    "--disable-features=Translate,MediaRouter,OptimizationHints", "--password-store=basic", "--use-mock-keychain",
    "--disable-search-engine-choice-screen", "--hide-scrollbars", "--mute-audio", "--remote-debugging-port=0",
];
// Ephemeral-only: a mock OS keystore avoids Keychain noise, but its key is not stable across runs,
// so it must NOT be used for a persistent profile (on-disk cookies would be undecryptable next launch).
const EPHEMERAL_ARGS: &[&str] = &["--use-mock-keychain"];

pub struct Browser {
    pub cdp: Cdp,
    pub child: Child,
    pub headless: bool,
    pub version: String,
    _user_data: PathBuf,
    persistent: bool,  // profile dir: keep it on close (do not delete)
}

fn playwright_cache() -> PathBuf {
    if let Ok(p) = std::env::var("PLAYWRIGHT_BROWSERS_PATH") { return PathBuf::from(p); }
    let home = std::env::var("HOME").unwrap_or_default();
    if cfg!(target_os = "macos") { Path::new(&home).join("Library/Caches/ms-playwright") } else { Path::new(&home).join(".cache/ms-playwright") }
}

/// Newest matching build dir under Playwright's cache, e.g. chromium_headless_shell-1234.
fn newest(prefix: &str) -> Option<PathBuf> {
    let mut dirs: Vec<(u32, PathBuf)> = std::fs::read_dir(playwright_cache()).ok()?.flatten()
        .filter_map(|e| { let n = e.file_name().into_string().ok()?; let rest = n.strip_prefix(prefix)?; let v: u32 = rest.parse().ok()?; Some((v, e.path())) }).collect();
    dirs.sort();
    dirs.pop().map(|(_, p)| p)
}

/// Engine choice persisted by `browser engine`: "managed" (pinned Chrome for Testing), "system"
/// (an installed browser), an explicit binary path, or unset = auto (managed if cached, else system).
pub fn config_engine() -> Option<String> {
    let p = Path::new(&std::env::var("HOME").unwrap_or_default()).join(".browser-daemon/config.json");
    let v: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(p).ok()?).ok()?;
    v.get("engine")?.as_str().map(String::from)
}

/// Installed Chromium-family browsers, most preferred first.
pub fn system_browsers() -> Vec<(String, PathBuf)> {
    let mut out = Vec::new();
    if cfg!(target_os = "macos") {
        for (name, p) in [
            ("Google Chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            ("Microsoft Edge", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            ("Brave", "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
            ("Chromium", "/Applications/Chromium.app/Contents/MacOS/Chromium"),
            ("Vivaldi", "/Applications/Vivaldi.app/Contents/MacOS/Vivaldi"),
        ] { let pb = PathBuf::from(p); if pb.exists() { out.push((name.to_string(), pb)); } }
    } else {
        for name in ["google-chrome", "google-chrome-stable", "microsoft-edge", "brave-browser", "chromium", "chromium-browser"] {
            for dir in ["/usr/bin", "/usr/local/bin", "/opt/homebrew/bin", "/snap/bin"] {
                let pb = Path::new(dir).join(name);
                if pb.exists() { out.push((name.to_string(), pb)); break; }
            }
        }
    }
    out
}

fn managed_executable(headless: bool) -> Option<PathBuf> {
    let arch = if cfg!(target_arch = "aarch64") { "arm64" } else { "x64" };
    let candidates: Vec<PathBuf> = if headless {
        newest("chromium_headless_shell-").into_iter().flat_map(|d| vec![
            d.join(format!("chrome-headless-shell-mac-{arch}/chrome-headless-shell")),
            d.join("chrome-headless-shell-linux64/chrome-headless-shell"), d.join("chrome-headless-shell-linux/chrome-headless-shell")]).collect()
    } else { vec![] };
    let mut all = candidates;
    if let Some(d) = newest("chromium-") {
        all.push(d.join(format!("chrome-mac-{arch}/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")));
        all.push(d.join("chrome-mac/Chromium.app/Contents/MacOS/Chromium"));
        all.push(d.join("chrome-linux64/chrome")); all.push(d.join("chrome-linux/chrome"));
    }
    for (prefix, names) in [("chromium_headless_shell-", &["chrome-headless-shell", "headless_shell"][..]), ("chromium-", &["Google Chrome for Testing", "chrome", "Chromium"][..])] {
        if headless != prefix.starts_with("chromium_headless") { continue; }
        if let Some(d) = newest(prefix) { if let Some(p) = find_binary(&d, names, 5) { all.push(p); } }
    }
    all.into_iter().find(|p| p.exists())
}

/// Persisted profile name (a CLI-owned Chrome user-data-dir), set via `browser profile <name>`.
pub fn config_profile() -> Option<String> {
    let p = Path::new(&std::env::var("HOME").unwrap_or_default()).join(".browser-daemon/config.json");
    let v: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(p).ok()?).ok()?;
    v.get("profile")?.as_str().filter(|s| !s.is_empty()).map(String::from)
}

pub fn profile_dir(name: &str) -> PathBuf {
    Path::new(&std::env::var("HOME").unwrap_or_default()).join(".browser-daemon/profiles").join(name)
}

pub fn find_executable(headless: bool) -> Result<PathBuf, String> {
    if let Ok(p) = std::env::var("BROWSER_CHROME_PATH") { return Ok(PathBuf::from(p)); }
    match config_engine().as_deref() {
        Some("managed") => managed_executable(headless).ok_or_else(|| "engine=managed but no downloaded build; run `browser install`".into()),
        Some("system") => system_browsers().into_iter().map(|(_, p)| p).next().ok_or_else(|| "engine=system but no installed Chromium-family browser found; run `browser engine managed` or install Chrome".into()),
        Some(path) if path != "auto" => { let p = PathBuf::from(path); if p.exists() { Ok(p) } else { Err(format!("engine path {path} does not exist; fix with `browser engine <path>|system|managed`")) } }
        _ => managed_executable(headless).or_else(|| system_browsers().into_iter().map(|(_, p)| p).next())
            .ok_or_else(|| "No Chromium found. Run `browser install` (downloads Chrome for Testing, ~196 MB), install Chrome, or set BROWSER_CHROME_PATH.".into()),
    }
}

fn find_binary(dir: &Path, names: &[&str], depth: u32) -> Option<PathBuf> {
    if depth == 0 { return None; }
    let mut subdirs = Vec::new();
    for e in std::fs::read_dir(dir).ok()?.flatten() {
        let p = e.path();
        if p.is_file() && names.iter().any(|n| p.file_name().map(|f| f == *n).unwrap_or(false)) { return Some(p); }
        if p.is_dir() { subdirs.push(p); }
    }
    subdirs.iter().find_map(|d| find_binary(d, names, depth - 1))
}

pub async fn launch(headless: bool) -> Result<Browser, String> {
    if find_executable(headless).is_err() {
        // e.g. headless-only install and the first `show`: fetch the missing build now
        tokio::task::spawn_blocking(move || crate::install::ensure(headless)).await.map_err(|e| e.to_string())??;
    }
    launch_in(headless, None).await
}

/// Launch, optionally in a persistent on-disk profile dir (for `browser profile`).
pub async fn launch_in(headless: bool, profile: Option<PathBuf>) -> Result<Browser, String> {
    let exe = find_executable(headless)?;
    let persistent = profile.is_some();
    let user_data = profile.unwrap_or_else(|| std::env::temp_dir().join(format!("browser-daemon-{}-{}", if headless { "headless" } else { "headed" }, std::process::id())));
    let mut cmd = Command::new(&exe);
    cmd.args(LAUNCH_ARGS).arg(format!("--user-data-dir={}", user_data.display()));
    if !persistent { cmd.args(EPHEMERAL_ARGS); }  // persistent profiles use the real OS keystore for stable cookie encryption
    if headless { cmd.arg("--headless"); } else { cmd.arg("--window-size=1280,900"); }
    if cfg!(target_os = "linux") { cmd.arg("--no-sandbox"); }
    cmd.arg("about:blank").stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::piped()).kill_on_drop(true);
    let mut child = cmd.spawn().map_err(|e| format!("launch {}: {e}", exe.display()))?;
    let stderr = child.stderr.take().ok_or("no stderr")?;
    let mut lines = BufReader::new(stderr).lines();
    let ws = tokio::time::timeout(std::time::Duration::from_secs(20), async {
        while let Ok(Some(line)) = lines.next_line().await {
            if let Some(i) = line.find("ws://") { return Some(line[i..].trim().to_string()); }
        }
        None
    }).await.map_err(|_| "Chromium did not print a DevTools URL in 20s")?.ok_or("Chromium exited before printing a DevTools URL")?;
    tokio::spawn(async move { while let Ok(Some(_)) = lines.next_line().await {} }); // drain stderr
    let cdp = Cdp::connect(&ws).await?;
    let v = cdp.send(None, "Browser.getVersion", serde_json::json!({})).await?;
    let version = v.get("product").and_then(|p| p.as_str()).unwrap_or("Chrome/0").to_string();
    eprintln!("[daemon] using {} ({})", exe.display(), version);
    Ok(Browser { cdp, child, headless, version, _user_data: user_data, persistent })
}

impl Browser {
    pub async fn close(&mut self) {
        // Ask Chrome to shut down gracefully and WAIT for it to exit — a persistent profile only
        // commits batched cookie writes to its on-disk store on a clean shutdown; SIGKILL loses them.
        let _ = tokio::time::timeout(std::time::Duration::from_secs(3), self.cdp.send(None, "Browser.close", serde_json::json!({}))).await;
        match tokio::time::timeout(std::time::Duration::from_secs(8), self.child.wait()).await {
            Ok(_) => {}
            Err(_) => { let _ = self.child.kill().await; }
        }
        if !self.persistent { let _ = std::fs::remove_dir_all(&self._user_data); }
    }
    pub fn user_agent(&self) -> String {
        let major = self.version.split('/').nth(1).and_then(|v| v.split('.').next()).unwrap_or("145");
        format!("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36")
    }
}
