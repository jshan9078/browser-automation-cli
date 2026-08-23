//! Page actions on top of raw CDP: navigate, snapshot, click/type/press via Input events, etc.
//! Every action returns the same JSON shape the Python daemon produced.
use crate::cdp::Cdp;
use crate::js;
use serde_json::{json, Map, Value};
use std::time::{Duration, Instant};

pub const ACTION_TIMEOUT_MS: u64 = 10_000;

/// A CDP session attached to one page target.
#[derive(Clone)]
pub struct Page {
    pub cdp: Cdp,
    pub sid: String,
    /// in-flight network requests, maintained from Network.* events by the session manager
    pub inflight: std::sync::Arc<std::sync::atomic::AtomicI64>,
}

impl Page {
    pub async fn send(&self, method: &str, params: Value) -> Result<Value, String> { self.cdp.send(Some(&self.sid), method, params).await }

    /// Evaluate a function expression with JSON args in the page's main world; returns the JSON value.
    pub async fn call(&self, fn_src: &str, args: &[Value]) -> Result<Value, String> {
        let args_src: Vec<String> = args.iter().map(|a| a.to_string()).collect();
        let expr = format!("{}\n;({})({})", js::LIB, fn_src, args_src.join(","));
        let r = self.send("Runtime.evaluate", json!({"expression": expr, "awaitPromise": true, "returnByValue": true, "userGesture": true})).await?;
        if let Some(ex) = r.get("exceptionDetails") {
            let msg = ex.pointer("/exception/description").or(ex.get("text")).and_then(|v| v.as_str()).unwrap_or("evaluation failed");
            return Err(msg.lines().next().unwrap_or(msg).to_string());
        }
        Ok(r.pointer("/result/value").cloned().unwrap_or(Value::Null))
    }

    pub async fn eval(&self, expression: &str) -> Result<Value, String> {
        let r = self.send("Runtime.evaluate", json!({"expression": expression, "awaitPromise": true, "returnByValue": true})).await?;
        if let Some(ex) = r.get("exceptionDetails") {
            let msg = ex.pointer("/exception/description").or(ex.get("text")).and_then(|v| v.as_str()).unwrap_or("evaluation failed");
            return Err(msg.lines().next().unwrap_or(msg).to_string());
        }
        Ok(r.pointer("/result/value").cloned().unwrap_or(Value::Null))
    }

    pub async fn url(&self) -> String { self.eval("location.href").await.ok().and_then(|v| v.as_str().map(String::from)).unwrap_or_default() }
    pub async fn title(&self) -> String { self.eval("document.title").await.ok().and_then(|v| v.as_str().map(String::from)).unwrap_or_default() }

    /// Wait until the DOM has been quiet for 60 ms (max 500 ms).
    pub async fn settle(&self) {
        let _ = self.wait_ready("interactive", 5000).await;
        let _ = tokio::time::timeout(Duration::from_millis(800), self.call(js::SETTLE, &[json!([60, 500])])).await;
    }

    /// Poll document.readyState until it reaches `state` ("interactive" or "complete").
    pub async fn wait_ready(&self, state: &str, timeout_ms: u64) -> Result<(), String> {
        let start = Instant::now();
        loop {
            let rs = self.eval("document.readyState").await.unwrap_or(Value::Null);
            let rs = rs.as_str().unwrap_or("");
            if rs == "complete" || (state == "interactive" && rs == "interactive") { return Ok(()); }
            if start.elapsed() > Duration::from_millis(timeout_ms) { return Err(format!("Timeout {timeout_ms}ms exceeded waiting for {state}")); }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    }

    async fn after(&self, mut result: Map<String, Value>, snap: bool, settle: bool) -> Value {
        if settle || snap { self.settle().await; }
        result.insert("url".into(), json!(self.url().await));
        result.insert("title".into(), json!(self.title().await));
        if snap {
            let s = snapshot(self, None, false, 300, "text").await;
            result.insert("snapshot".into(), s.get("snapshot").or(s.get("error")).cloned().unwrap_or(Value::Null));
        }
        Value::Object(result)
    }

    /// Resolve a target with retries (actionability) up to the timeout.
    async fn resolve(&self, t: &Value, timeout_ms: u64) -> Result<Value, String> {
        let start = Instant::now();
        loop {
            let r = self.call(js::RESOLVE, &[t.clone()]).await?;
            if r.get("ok").and_then(|v| v.as_bool()).unwrap_or(false) { return Ok(r); }
            let reason = r.get("reason").and_then(|v| v.as_str()).unwrap_or("cannot resolve target").to_string();
            if r.get("fatal").and_then(|v| v.as_bool()).unwrap_or(false) { return Err(reason); }
            if start.elapsed() > Duration::from_millis(timeout_ms) { return Err(format!("Timeout {timeout_ms}ms exceeded: {reason}")); }
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
    }

    async fn mouse(&self, kind: &str, x: f64, y: f64, button: &str, clicks: u32, modifiers: u32) -> Result<(), String> {
        self.send("Input.dispatchMouseEvent", json!({"type": kind, "x": x, "y": y, "button": button, "clickCount": clicks, "modifiers": modifiers})).await.map(|_| ())
    }

    async fn click_at(&self, x: f64, y: f64, clicks: u32) -> Result<(), String> {
        self.mouse("mouseMoved", x, y, "none", 0, 0).await?;
        for c in 1..=clicks {
            self.mouse("mousePressed", x, y, "left", c, 0).await?;
            self.mouse("mouseReleased", x, y, "left", c, 0).await?;
        }
        Ok(())
    }
}

fn target_of(p: &Map<String, Value>) -> Value {
    let mut t = Map::new();
    t.insert("target".into(), p.get("selector").cloned().unwrap_or(json!("")));
    for k in ["text", "role", "name", "label", "placeholder"] { if let Some(v) = p.get(k) { if !v.is_null() { t.insert(k.into(), v.clone()); } } }
    Value::Object(t)
}
fn has_target(p: &Map<String, Value>) -> bool {
    p.get("selector").and_then(|v| v.as_str()).map(|s| !s.is_empty()).unwrap_or(false) || ["text", "role", "name", "label", "placeholder"].iter().any(|k| p.get(*k).map(|v| !v.is_null()).unwrap_or(false))
}
fn flag(p: &Map<String, Value>, k: &str) -> bool { p.get(k).and_then(|v| v.as_bool()).unwrap_or(false) }
fn s(p: &Map<String, Value>, k: &str) -> String { p.get(k).and_then(|v| v.as_str()).unwrap_or("").to_string() }
fn fail(msg: impl Into<String>) -> Value { json!({"success": false, "error": msg.into()}) }
fn ok() -> Map<String, Value> { let mut m = Map::new(); m.insert("success".into(), json!(true)); m }

// ---------------------------------------------------------------------------

pub async fn navigate(page: &Page, p: &Map<String, Value>) -> Value {
    let url = s(p, "url");
    let wait = p.get("wait").and_then(|v| v.as_str()).unwrap_or("load").to_string();
    let timeout = p.get("timeout").and_then(|v| v.as_f64()).unwrap_or(30_000.0) as u64;
    let snap = flag(p, "snap");
    let r = match page.send("Page.navigate", json!({"url": url})).await { Ok(r) => r, Err(e) => return fail(format!("Navigation failed: {e}")) };
    if let Some(err) = r.get("errorText").and_then(|v| v.as_str()) { return fail(format!("Navigation failed: {err}")); }
    let mut res = ok();
    let mut settled = true;
    if wait != "commit" {
        let state = if wait == "domcontentloaded" { "interactive" } else { "complete" };
        if let Err(e) = page.wait_ready(state, timeout).await {
            settled = false;
            res.insert("warning".into(), json!(e));
        }
        if wait == "networkidle" && settled {
            // real networkidle: no in-flight requests for 500 ms (bounded to 5 s); long-polling pages never get there
            let start = Instant::now(); let mut quiet_since = Instant::now();
            loop {
                let inflight = page.inflight.load(std::sync::atomic::Ordering::Relaxed);
                if inflight > 0 { quiet_since = Instant::now(); }
                if quiet_since.elapsed() > Duration::from_millis(500) { break; }
                if start.elapsed() > Duration::from_secs(5) { settled = false; break; }
                tokio::time::sleep(Duration::from_millis(50)).await;
            }
        }
    }
    res.insert("settled".into(), json!(settled));
    page.after(res, snap, true).await
}

pub fn format_snapshot(res: &Value) -> String {
    let mut lines = vec![format!("url: {}", res["url"].as_str().unwrap_or("")), format!("title: {}", res["title"].as_str().unwrap_or(""))];
    let (dh, vh, sy) = (res["documentHeight"].as_i64().unwrap_or(0), res["viewportHeight"].as_i64().unwrap_or(0), res["scrollY"].as_i64().unwrap_or(0));
    if dh > vh + 10 { lines.push(format!("scroll: {sy}/{} (viewport {}x{vh}; [below]/[above] = outside viewport)", dh - vh, res["viewportWidth"].as_i64().unwrap_or(0))); }
    for e in res["elements"].as_array().cloned().unwrap_or_default() {
        let mut parts: Vec<String> = Vec::new();
        if let Some(r) = e.get("ref").and_then(|v| v.as_str()) { parts.push(format!("@{r}")); }
        let role = e["role"].as_str().unwrap_or("");
        parts.push(if role == "heading" { format!("h{}", e.get("level").and_then(|v| v.as_i64()).unwrap_or(2)) } else { role.to_string() });
        if let Some(n) = e.get("name").and_then(|v| v.as_str()).filter(|n| !n.is_empty()) { parts.push(format!("\"{}\"", n.replace('"', "\\\""))); }
        for k in ["href", "placeholder", "value", "type"] { if let Some(v) = e.get(k).and_then(|v| v.as_str()).filter(|v| !v.is_empty()) { parts.push(format!("{k}=\"{v}\"")); } }
        if let Some(o) = e.get("options").and_then(|v| v.as_array()) { parts.push(format!("[{}]", o.iter().filter_map(|x| x.as_str()).collect::<Vec<_>>().join(" | "))); }
        for k in ["checked", "expanded"] { if let Some(b) = e.get(k).and_then(|v| v.as_bool()) { parts.push(format!("[{k}={b}]")); } }
        for k in ["selected", "disabled", "required", "frame"] { if e.get(k).and_then(|v| v.as_bool()).unwrap_or(false) { parts.push(format!("[{k}]")); } }
        if let Some(pos) = e.get("pos").and_then(|v| v.as_str()).filter(|p| !p.is_empty()) { parts.push(format!("[{pos}]")); }
        lines.push(parts.join(" "));
    }
    if let Some(t) = res.get("truncated").and_then(|v| v.as_i64()).filter(|t| *t > 0) { lines.push(format!("... {t} more element(s) truncated; scope with a selector or raise --max")); }
    lines.join("\n")
}

pub async fn snapshot(page: &Page, selector: Option<&str>, all: bool, max: i64, format: &str) -> Value {
    let r = match page.call(js::SNAPSHOT, &[json!({"scope": selector, "all": all, "max": max})]).await { Ok(r) => r, Err(e) => return fail(e) };
    if let Some(e) = r.get("error") { return fail(e.as_str().unwrap_or("snapshot failed")); }
    if format == "json" { let mut m = r.as_object().cloned().unwrap_or_default(); m.insert("success".into(), json!(true)); return Value::Object(m); }
    json!({"success": true, "snapshot": format_snapshot(&r)})
}

pub async fn snapshot_p(page: &Page, p: &Map<String, Value>) -> Value {
    snapshot(page, p.get("selector").and_then(|v| v.as_str()), flag(p, "all"), p.get("max").and_then(|v| v.as_i64()).unwrap_or(300), p.get("format").and_then(|v| v.as_str()).unwrap_or("text")).await
}

pub async fn click(page: &Page, p: &Map<String, Value>) -> Value {
    let r = match page.resolve(&target_of(p), ACTION_TIMEOUT_MS).await { Ok(r) => r, Err(e) => return fail(e) };
    let (x, y) = (r["x"].as_f64().unwrap_or(0.0), r["y"].as_f64().unwrap_or(0.0));
    if let Err(e) = page.click_at(x, y, if flag(p, "double") { 2 } else { 1 }).await { return fail(e); }
    page.after(ok(), flag(p, "snap"), true).await
}

pub async fn hover(page: &Page, p: &Map<String, Value>) -> Value {
    let r = match page.resolve(&target_of(p), ACTION_TIMEOUT_MS).await { Ok(r) => r, Err(e) => return fail(e) };
    if let Err(e) = page.mouse("mouseMoved", r["x"].as_f64().unwrap_or(0.0), r["y"].as_f64().unwrap_or(0.0), "none", 0, 0).await { return fail(e); }
    page.after(ok(), flag(p, "snap"), true).await
}

pub async fn type_text(page: &Page, p: &Map<String, Value>) -> Value {
    let text = s(p, "text_value");
    let r = match page.resolve(&target_of(p), ACTION_TIMEOUT_MS).await { Ok(r) => r, Err(e) => return fail(e) };
    if !r["editable"].as_bool().unwrap_or(false) && r["tag"].as_str() != Some("select") {
        // click to focus whatever it is (e.g. a custom widget), then type
        let _ = page.click_at(r["x"].as_f64().unwrap_or(0.0), r["y"].as_f64().unwrap_or(0.0), 1).await;
    }
    let f = match page.call(js::FOCUS_SELECT_ALL, &[]).await { Ok(f) => f, Err(e) => return fail(e) };
    if !f["ok"].as_bool().unwrap_or(false) { return fail(f["reason"].as_str().unwrap_or("cannot focus target")); }
    if let Err(e) = page.call(js::CLEAR, &[]).await { return fail(e); }
    if flag(p, "sequential") {
        for ch in text.chars() { if let Err(e) = press_char(page, ch).await { return fail(e); } }
    } else if !text.is_empty() {
        if let Err(e) = page.send("Input.insertText", json!({"text": text})).await { return fail(e); }
    }
    let submit = flag(p, "submit");
    if submit { if let Err(e) = press_key_combo(page, "Enter").await { return fail(e); } }
    page.after(ok(), flag(p, "snap"), submit).await
}

pub async fn select_option(page: &Page, p: &Map<String, Value>) -> Value {
    if let Err(e) = page.resolve(&target_of(p), ACTION_TIMEOUT_MS).await { return fail(e); }
    match page.call(js::SELECT_OPTION, &[json!(s(p, "value"))]).await {
        Ok(r) if r["ok"].as_bool().unwrap_or(false) => page.after(ok(), flag(p, "snap"), true).await,
        Ok(r) => fail(r["reason"].as_str().unwrap_or("select failed")),
        Err(e) => fail(e),
    }
}

// ---- keyboard ----------------------------------------------------------------
struct KeyDef { key: &'static str, code: &'static str, vk: u32, text: &'static str }
const KEYS: &[KeyDef] = &[
    KeyDef { key: "Enter", code: "Enter", vk: 13, text: "\r" }, KeyDef { key: "Tab", code: "Tab", vk: 9, text: "" },
    KeyDef { key: "Escape", code: "Escape", vk: 27, text: "" }, KeyDef { key: "Backspace", code: "Backspace", vk: 8, text: "" },
    KeyDef { key: "Delete", code: "Delete", vk: 46, text: "" }, KeyDef { key: " ", code: "Space", vk: 32, text: " " },
    KeyDef { key: "ArrowUp", code: "ArrowUp", vk: 38, text: "" }, KeyDef { key: "ArrowDown", code: "ArrowDown", vk: 40, text: "" },
    KeyDef { key: "ArrowLeft", code: "ArrowLeft", vk: 37, text: "" }, KeyDef { key: "ArrowRight", code: "ArrowRight", vk: 39, text: "" },
    KeyDef { key: "Home", code: "Home", vk: 36, text: "" }, KeyDef { key: "End", code: "End", vk: 35, text: "" },
    KeyDef { key: "PageUp", code: "PageUp", vk: 33, text: "" }, KeyDef { key: "PageDown", code: "PageDown", vk: 34, text: "" },
    KeyDef { key: "F1", code: "F1", vk: 112, text: "" }, KeyDef { key: "F5", code: "F5", vk: 116, text: "" },
];

fn key_def(name: &str) -> (String, String, u32, String) {
    let n = if name.eq_ignore_ascii_case("space") { " " } else if name.eq_ignore_ascii_case("esc") { "Escape" } else if name.eq_ignore_ascii_case("return") { "Enter" } else { name };
    if let Some(k) = KEYS.iter().find(|k| k.key.eq_ignore_ascii_case(n) || k.code.eq_ignore_ascii_case(n)) { return (k.key.into(), k.code.into(), k.vk, k.text.into()); }
    let mut chars = n.chars();
    if let (Some(c), None) = (chars.next(), chars.next()) {
        let up = c.to_ascii_uppercase();
        let code = if c.is_ascii_alphabetic() { format!("Key{up}") } else if c.is_ascii_digit() { format!("Digit{c}") } else { String::new() };
        return (c.to_string(), code, up as u32, c.to_string());
    }
    (n.to_string(), n.to_string(), 0, String::new())
}

async fn press_char(page: &Page, c: char) -> Result<(), String> { press_key_combo(page, &c.to_string()).await }

/// "Control+Shift+a", "Enter", "Alt+ArrowUp"
pub async fn press_key_combo(page: &Page, combo: &str) -> Result<(), String> {
    let parts: Vec<&str> = combo.split('+').collect();
    let (mods_s, key_s) = parts.split_at(parts.len() - 1);
    let mut modifiers = 0u32;
    for m in mods_s { modifiers |= match m.to_ascii_lowercase().as_str() { "alt" | "option" => 1, "control" | "ctrl" => 2, "meta" | "cmd" | "command" => 4, "shift" => 8, _ => 0 }; }
    let (key, code, vk, text) = key_def(key_s[0]);
    let text = if modifiers & !8 != 0 { String::new() } else { text };
    let mut down = json!({"type": if text.is_empty() { "rawKeyDown" } else { "keyDown" }, "key": key, "code": code, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk, "modifiers": modifiers});
    if !text.is_empty() { down["text"] = json!(text); down["unmodifiedText"] = json!(text); }
    if modifiers & 4 != 0 && cfg!(target_os = "macos") {
        // macOS editing shortcuts are not synthesized from key events alone; map the common ones
        let cmd = match key.to_ascii_lowercase().as_str() { "a" => Some("selectAll"), "c" => Some("copy"), "v" => Some("paste"), "x" => Some("cut"), "z" => Some("undo"), _ => None };
        if let Some(c) = cmd { down["commands"] = json!([c]); }
    }
    page.send("Input.dispatchKeyEvent", down).await?;
    page.send("Input.dispatchKeyEvent", json!({"type": "keyUp", "key": key, "code": code, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk, "modifiers": modifiers})).await?;
    Ok(())
}

pub async fn press_key(page: &Page, p: &Map<String, Value>) -> Value {
    if has_target(p) { if let Err(e) = page.resolve(&target_of(p), ACTION_TIMEOUT_MS).await { return fail(e); } if let Err(e) = page.call("() => { window.__btarget && window.__btarget.focus(); return true; }", &[]).await { return fail(e); } }
    if let Err(e) = press_key_combo(page, &s(p, "key")).await { return fail(e); }
    page.after(ok(), flag(p, "snap"), true).await
}

pub async fn scroll(page: &Page, p: &Map<String, Value>) -> Value {
    if has_target(p) {
        if let Err(e) = page.resolve(&target_of(p), ACTION_TIMEOUT_MS).await { return fail(e); } // resolve scrolls into view
    } else {
        let vh = page.eval("window.innerHeight").await.ok().and_then(|v| v.as_f64()).unwrap_or(800.0);
        let vw = page.eval("window.innerWidth").await.ok().and_then(|v| v.as_f64()).unwrap_or(1280.0);
        let mut dy = p.get("amount").and_then(|v| v.as_f64()).unwrap_or(vh * 0.8);
        if s(p, "direction") == "up" { dy = -dy; }
        if let Err(e) = page.send("Input.dispatchMouseEvent", json!({"type": "mouseWheel", "x": vw / 2.0, "y": vh / 2.0, "deltaX": 0, "deltaY": dy})).await { return fail(e); }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    page.after(ok(), flag(p, "snap"), true).await
}

pub async fn get_text(page: &Page, p: &Map<String, Value>) -> Value {
    let sel = p.get("selector").and_then(|v| v.as_str()).unwrap_or("body");
    let max = p.get("max").and_then(|v| v.as_i64()).unwrap_or(20_000);
    match page.call(js::TEXT, &[json!(sel), json!(max)]).await {
        Ok(r) if r.get("error").is_some() => fail(r["error"].as_str().unwrap_or("text failed")),
        Ok(r) => json!({"success": true, "text": r["text"], "truncated": r["truncated"]}),
        Err(e) => fail(e),
    }
}

pub async fn evaluate(page: &Page, p: &Map<String, Value>) -> Value {
    match page.eval(&s(p, "expression")).await { Ok(v) => json!({"success": true, "result": v}), Err(e) => fail(e) }
}

pub async fn wait_for(page: &Page, p: &Map<String, Value>) -> Value {
    let timeout = p.get("timeout").and_then(|v| v.as_f64()).unwrap_or(10_000.0) as u64;
    let (text, sel, gone) = (p.get("text").cloned().unwrap_or(Value::Null), p.get("selector").cloned().unwrap_or(Value::Null), flag(p, "gone"));
    if text.is_null() && sel.is_null() { tokio::time::sleep(Duration::from_millis(timeout.min(30_000))).await; return json!({"success": true}); }
    let start = Instant::now();
    loop {
        if let Ok(v) = page.call(js::WAIT_CHECK, &[text.clone(), sel.clone(), json!(gone)]).await { if v.as_bool().unwrap_or(false) { return json!({"success": true}); } }
        if start.elapsed() > Duration::from_millis(timeout) { return fail(format!("Timeout {timeout}ms exceeded waiting for {}", if !text.is_null() { format!("text {text}") } else { format!("selector {sel}") })); }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
}

pub async fn screenshot(page: &Page, p: &Map<String, Value>, session_id: &str) -> Value {
    use base64::Engine;
    let quality = p.get("quality").and_then(|v| v.as_i64()).unwrap_or(70);
    let mut params = json!({"format": "jpeg", "quality": quality});
    if has_target(p) {
        let r = match page.resolve(&target_of(p), ACTION_TIMEOUT_MS).await { Ok(r) => r, Err(e) => return fail(e) };
        let b = r["box"].as_array().cloned().unwrap_or_default();
        if b.len() == 4 { params["clip"] = json!({"x": b[0], "y": b[1], "width": b[2], "height": b[3], "scale": 1}); }
    } else if flag(p, "full_page") {
        if let Ok(m) = page.send("Page.getLayoutMetrics", json!({})).await {
            let w = m.pointer("/cssContentSize/width").and_then(|v| v.as_f64()).unwrap_or(1280.0);
            let h = m.pointer("/cssContentSize/height").and_then(|v| v.as_f64()).unwrap_or(800.0);
            params["clip"] = json!({"x": 0, "y": 0, "width": w, "height": h, "scale": 1});
            params["captureBeyondViewport"] = json!(true);
        }
    }
    let r = match page.send("Page.captureScreenshot", params).await { Ok(r) => r, Err(e) => return fail(e) };
    let data = match base64::engine::general_purpose::STANDARD.decode(r["data"].as_str().unwrap_or("")) { Ok(d) => d, Err(e) => return fail(e.to_string()) };
    let path = match p.get("output").and_then(|v| v.as_str()) {
        Some(o) => std::path::PathBuf::from(if let Some(rest) = o.strip_prefix("~/") { format!("{}/{}", std::env::var("HOME").unwrap_or_default(), rest) } else { o.to_string() }),
        None => {
            let dir = std::path::Path::new(&std::env::var("HOME").unwrap_or_default()).join(".browser-daemon").join("shots");
            let _ = std::fs::create_dir_all(&dir); set_mode(&dir, 0o700);
            dir.join(format!("{}_{}.jpg", session_id, std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_millis()).unwrap_or(0)))
        }
    };
    if let Err(e) = std::fs::write(&path, &data) { return fail(format!("write {}: {e}", path.display())); }
    set_mode(&path, 0o600);
    json!({"success": true, "path": path.to_string_lossy(), "bytes": data.len(), "format": "jpeg"})
}

pub fn set_mode(p: &std::path::Path, mode: u32) {
    #[cfg(unix)] { use std::os::unix::fs::PermissionsExt; let _ = std::fs::set_permissions(p, std::fs::Permissions::from_mode(mode)); }
}

pub async fn history(page: &Page, p: &Map<String, Value>, delta: i64) -> Value {
    let h = match page.send("Page.getNavigationHistory", json!({})).await { Ok(h) => h, Err(e) => return fail(e) };
    let idx = h["currentIndex"].as_i64().unwrap_or(0) + delta;
    let entries = h["entries"].as_array().cloned().unwrap_or_default();
    let Some(entry) = entries.get(idx.max(0) as usize).filter(|_| idx >= 0) else { return fail(if delta < 0 { "cannot go back: no previous entry" } else { "cannot go forward: no next entry" }); };
    if let Err(e) = page.send("Page.navigateToHistoryEntry", json!({"entryId": entry["id"]})).await { return fail(e); }
    let _ = page.wait_ready("interactive", 15_000).await;
    page.after(ok(), flag(p, "snap"), true).await
}
