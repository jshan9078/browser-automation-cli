//! Sessions: one browser context + one page each, living in the headless or the headed browser.
//! Idle hidden sessions are frozen (script execution disabled) and, later, hibernated to disk.
use crate::actions::{self, Page};
use crate::chrome::{self, Browser};
use crate::js;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{HashMap, VecDeque};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tokio::sync::Mutex;

pub const VIEWPORT: (u32, u32) = (1280, 800);
const CONSOLE_MAX: usize = 200;

fn env_f(k: &str, d: f64) -> f64 { std::env::var(k).ok().and_then(|v| v.parse().ok()).unwrap_or(d) }
pub fn freeze_after() -> f64 { env_f("BROWSER_FREEZE_AFTER", 10.0) }
pub fn hibernate_after() -> f64 { env_f("BROWSER_HIBERNATE_AFTER", 600.0) }
pub fn state_dir() -> PathBuf { PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".browser-daemon").join("sessions") }
fn now() -> f64 { SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0) }

#[derive(Serialize, Deserialize, Clone, Default, Debug)]
pub struct SavedState {
    #[serde(default)] pub cookies: Vec<Value>,
    #[serde(default)] pub local_storage: Vec<Value>, // [{origin, items}]
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct Persisted { url: String, state: Option<SavedState>, created_at: f64, title: String, #[serde(default)] visible: bool }

pub struct Live {
    pub page: Page,
    pub context_id: String,
    pub target_id: String,
    pub headless: bool,
}

pub struct Session {
    pub id: String,
    pub visible: bool,
    pub live: Option<Live>,
    pub created_at: f64,
    pub last_used: Instant,
    pub frozen: bool,
    pub busy: u32,
    pub title: String,
    pub saved_url: String,
    pub saved_state: Option<SavedState>,
    pub console: VecDeque<Value>,
}

pub struct Browsers { pub headless: Option<Browser>, pub headed: Option<Browser> }

pub struct Manager {
    pub sessions: HashMap<String, Session>,
    pub browsers: Browsers,
}

pub type Shared = Arc<Mutex<Manager>>;

impl Manager {
    pub fn new() -> Manager {
        let mut m = Manager { sessions: HashMap::new(), browsers: Browsers { headless: None, headed: None } };
        let dir = state_dir();
        let _ = std::fs::create_dir_all(&dir); actions::set_mode(&dir, 0o700);
        if let Ok(rd) = std::fs::read_dir(&dir) {
            for e in rd.flatten() {
                let p = e.path();
                if p.extension().map(|x| x == "json").unwrap_or(false) {
                    if let Ok(txt) = std::fs::read_to_string(&p) {
                        if let Ok(ps) = serde_json::from_str::<Persisted>(&txt) {
                            let id = p.file_stem().unwrap().to_string_lossy().to_string();
                            m.sessions.insert(id.clone(), Session { id, visible: ps.visible, live: None, created_at: ps.created_at, last_used: Instant::now(), frozen: false, busy: 0, title: ps.title, saved_url: ps.url, saved_state: ps.state, console: VecDeque::new() });
                        }
                    }
                }
            }
        }
        if !m.sessions.is_empty() { eprintln!("[daemon] loaded {} hibernated session(s)", m.sessions.len()); }
        m
    }

    pub async fn browser(&mut self, headless: bool) -> Result<&mut Browser, String> {
        let slot = if headless { &mut self.browsers.headless } else { &mut self.browsers.headed };
        if slot.as_ref().map(|b| !b.cdp.is_alive()).unwrap_or(true) {
            eprintln!("[daemon] launching {} browser", if headless { "headless" } else { "headed" });
            *slot = Some(chrome::launch(headless).await?);
        }
        Ok(slot.as_mut().unwrap())
    }

    pub async fn close_idle_browsers(&mut self) {
        let live_visible = self.sessions.values().any(|s| s.live.as_ref().map(|l| !l.headless).unwrap_or(false));
        let live_hidden = self.sessions.values().any(|s| s.live.as_ref().map(|l| l.headless).unwrap_or(false));
        if !live_visible { if let Some(mut b) = self.browsers.headed.take() { eprintln!("[daemon] closing idle headed browser"); b.close().await; } }
        if !live_hidden { if let Some(mut b) = self.browsers.headless.take() { eprintln!("[daemon] closing idle headless browser"); b.close().await; } }
    }

    pub async fn close_all_browsers(&mut self) {
        if let Some(mut b) = self.browsers.headed.take() { b.close().await; }
        if let Some(mut b) = self.browsers.headless.take() { b.close().await; }
    }

    // ---- lifecycle --------------------------------------------------------
    async fn attach(&mut self, id: &str, visible: bool, url: Option<String>) -> Result<(), String> {
        let (saved_state, saved_url) = { let s = self.sessions.get(id).ok_or("no session")?; (s.saved_state.clone(), s.saved_url.clone()) };
        let headless = !visible;
        let ua = { let b = self.browser(headless).await?; b.user_agent() };
        let cdp = self.browser(headless).await?.cdp.clone();
        let ctx = cdp.send(None, "Target.createBrowserContext", json!({"disposeOnDetach": false})).await?;
        let context_id = ctx["browserContextId"].as_str().ok_or("no browserContextId")?.to_string();
        let mut create = json!({"url": "about:blank", "browserContextId": context_id});
        if !headless { create["newWindow"] = json!(true); create["width"] = json!(VIEWPORT.0); create["height"] = json!(VIEWPORT.1); }
        let t = cdp.send(None, "Target.createTarget", create).await?;
        let target_id = t["targetId"].as_str().ok_or("no targetId")?.to_string();
        let a = cdp.send(None, "Target.attachToTarget", json!({"targetId": target_id, "flatten": true})).await?;
        let sid = a["sessionId"].as_str().ok_or("no sessionId")?.to_string();
        let page = Page { cdp: cdp.clone(), sid: sid.clone(), inflight: std::sync::Arc::new(std::sync::atomic::AtomicI64::new(0)) };
        page.send("Page.enable", json!({})).await?;
        page.send("Runtime.enable", json!({})).await?;
        page.send("Network.enable", json!({})).await?;
        // track in-flight requests for networkidle
        { let inflight = page.inflight.clone(); let mut rx = cdp.subscribe(); let sid2 = sid.clone();
          tokio::spawn(async move { use std::sync::atomic::Ordering; let mut ids = std::collections::HashSet::new();
            loop { match rx.recv().await {
                Ok(ev) if ev.session_id.as_deref() == Some(&sid2) => { let rid = ev.params.get("requestId").and_then(|v| v.as_str()).unwrap_or("").to_string();
                    match ev.method.as_str() {
                        "Network.requestWillBeSent" => { if ids.insert(rid) { inflight.fetch_add(1, Ordering::Relaxed); } }
                        "Network.loadingFinished" | "Network.loadingFailed" | "Network.requestServedFromCache" => { if ids.remove(&rid) { inflight.fetch_sub(1, Ordering::Relaxed); } }
                        _ => {} } }
                Ok(_) => {}
                Err(tokio::sync::broadcast::error::RecvError::Lagged(_)) => {}
                Err(_) => break, } } }); }
        page.send("Network.setUserAgentOverride", json!({"userAgent": ua})).await?;
        page.send("Emulation.setDeviceMetricsOverride", json!({"width": VIEWPORT.0, "height": VIEWPORT.1, "deviceScaleFactor": 1, "mobile": false})).await?;
        page.send("Page.addScriptToEvaluateOnNewDocument", json!({"source": js::STEALTH})).await?;
        // a headed window that is not frontmost has no document focus, so insertText/key events are dropped
        let _ = page.send("Emulation.setFocusEmulationEnabled", json!({"enabled": true})).await;
        if let Some(st) = &saved_state {
            if !st.cookies.is_empty() { let _ = cdp.send(None, "Storage.setCookies", json!({"cookies": st.cookies, "browserContextId": context_id})).await; }
            if !st.local_storage.is_empty() {
                let src = format!("(() => {{ const all = {}; for (const e of all) {{ if (e.origin === location.origin) {{ try {{ for (const [k, v] of Object.entries(e.items)) if (localStorage.getItem(k) === null) localStorage.setItem(k, v); }} catch (x) {{}} }} }} }})();", serde_json::to_string(&st.local_storage).unwrap());
                let _ = page.send("Page.addScriptToEvaluateOnNewDocument", json!({"source": src})).await;
            }
        }
        let s = self.sessions.get_mut(id).unwrap();
        s.live = Some(Live { page: page.clone(), context_id, target_id, headless });
        s.visible = visible; s.frozen = false;
        let target = url.unwrap_or(saved_url);
        if !target.is_empty() && target != "about:blank" {
            let _ = page.send("Page.navigate", json!({"url": target})).await;
            let _ = page.wait_ready("interactive", 30_000).await;
        }
        Ok(())
    }

    async fn save(&mut self, id: &str) {
        let Some(s) = self.sessions.get_mut(id) else { return };
        if let Some(l) = &s.live {
            let cookies = l.page.cdp.send(None, "Storage.getCookies", json!({"browserContextId": l.context_id})).await.ok().and_then(|v| v["cookies"].as_array().cloned()).unwrap_or_default();
            let mut ls = s.saved_state.clone().unwrap_or_default().local_storage;
            if let Ok(v) = l.page.call(js::LOCAL_STORAGE_DUMP, &[]).await { if v.is_object() { let o = v["origin"].clone(); ls.retain(|e| e["origin"] != o); ls.push(v); } }
            s.saved_state = Some(SavedState { cookies, local_storage: ls });
            s.saved_url = l.page.url().await;
        }
        let p = Persisted { url: s.saved_url.clone(), state: s.saved_state.clone(), created_at: s.created_at, title: s.title.clone(), visible: s.visible };
        let f = state_dir().join(format!("{id}.json"));
        let _ = std::fs::write(&f, serde_json::to_string(&p).unwrap()); actions::set_mode(&f, 0o600);
    }

    async fn detach(&mut self, id: &str) {
        if self.sessions.get(id).map(|s| s.live.is_none()).unwrap_or(true) { return; }
        if self.sessions[id].frozen { self.set_frozen(id, false).await; }
        self.save(id).await;
        let s = self.sessions.get_mut(id).unwrap();
        if let Some(l) = s.live.take() {
            let _ = l.page.cdp.send(None, "Target.closeTarget", json!({"targetId": l.target_id})).await;
            let _ = l.page.cdp.send(None, "Target.disposeBrowserContext", json!({"browserContextId": l.context_id})).await;
        }
        s.frozen = false;
    }

    pub async fn set_frozen(&mut self, id: &str, frozen: bool) {
        let Some(s) = self.sessions.get_mut(id) else { return };
        if let Some(l) = &s.live {
            if l.page.send("Emulation.setScriptExecutionDisabled", json!({"value": frozen})).await.is_ok() { s.frozen = frozen; }
        }
    }

    pub async fn create(&mut self, visible: bool) -> Result<String, String> {
        let id = uuid::Uuid::new_v4().simple().to_string()[..8].to_string();
        self.sessions.insert(id.clone(), Session { id: id.clone(), visible, live: None, created_at: now(), last_used: Instant::now(), frozen: false, busy: 0, title: String::new(), saved_url: "about:blank".into(), saved_state: None, console: VecDeque::new() });
        if let Err(e) = self.attach(&id, visible, None).await { self.sessions.remove(&id); return Err(e); }
        self.save(&id).await;
        eprintln!("[daemon] created session {id} (visible={visible})");
        Ok(id)
    }

    /// Ready a session for a command: rehydrate if hibernated, thaw if frozen.
    pub async fn wake(&mut self, id: &str) -> Result<Page, String> {
        if !self.sessions.contains_key(id) { return Err(format!("Session {id} not found")); }
        if self.sessions[id].live.is_none() { let v = self.sessions[id].visible; self.attach(id, v, None).await?; }
        else if self.sessions[id].frozen { self.set_frozen(id, false).await; }
        let s = self.sessions.get_mut(id).unwrap();
        s.last_used = Instant::now(); s.busy += 1;
        Ok(s.live.as_ref().unwrap().page.clone())
    }

    pub fn done(&mut self, id: &str) { if let Some(s) = self.sessions.get_mut(id) { s.busy = s.busy.saturating_sub(1); s.last_used = Instant::now(); } }

    pub async fn set_visible(&mut self, id: &str, visible: bool) -> Result<(), String> {
        if !self.sessions.contains_key(id) { return Err("Session not found".into()); }
        let s = &self.sessions[id];
        if s.live.is_some() && s.visible == visible { return Ok(()); }
        let url = if let Some(l) = &s.live { l.page.url().await } else { s.saved_url.clone() };
        self.detach(id).await;
        self.attach(id, visible, Some(url)).await?;
        self.sessions.get_mut(id).unwrap().last_used = Instant::now();
        self.save(id).await;
        self.close_idle_browsers().await;
        Ok(())
    }

    pub fn list(&self) -> Value {
        let mut v: Vec<&Session> = self.sessions.values().collect();
        v.sort_by(|a, b| a.created_at.partial_cmp(&b.created_at).unwrap());
        json!(v.iter().map(|s| json!({"session_id": s.id, "url": s.saved_url_or_live(), "title": s.title,
            "state": if s.live.is_none() { "hibernated" } else if s.frozen { "frozen" } else { "active" }, "visible": s.visible})).collect::<Vec<_>>())
    }

    pub async fn delete(&mut self, id: &str) -> bool {
        if !self.sessions.contains_key(id) { return false; }
        if self.sessions[id].frozen { self.set_frozen(id, false).await; }
        if let Some(l) = self.sessions.get_mut(id).unwrap().live.take() {
            let _ = l.page.cdp.send(None, "Target.closeTarget", json!({"targetId": l.target_id})).await;
            let _ = l.page.cdp.send(None, "Target.disposeBrowserContext", json!({"browserContextId": l.context_id})).await;
        }
        self.sessions.remove(id);
        let _ = std::fs::remove_file(state_dir().join(format!("{id}.json")));
        eprintln!("[daemon] deleted session {id}");
        self.close_idle_browsers().await;
        true
    }

    pub async fn close_all(&mut self) {
        let ids: Vec<String> = self.sessions.keys().cloned().collect();
        for id in ids { self.detach(&id).await; }
        self.close_all_browsers().await;
    }

    /// Called once a second: freeze / hibernate idle hidden sessions, close unused browsers.
    pub async fn housekeep(&mut self) {
        let (fa, ha) = (freeze_after(), hibernate_after());
        let ids: Vec<String> = self.sessions.keys().cloned().collect();
        for id in ids {
            let s = &self.sessions[&id];
            if s.live.is_none() || s.busy > 0 { continue; }
            let idle = s.last_used.elapsed().as_secs_f64();
            if ha > 0.0 && idle > ha { eprintln!("[daemon] hibernating idle session {id}"); self.detach(&id).await; }
            else if fa > 0.0 && !s.visible && !s.frozen && idle > fa { self.set_frozen(&id, true).await; }
        }
        self.close_idle_browsers().await;
    }

    pub fn push_console(&mut self, cdp_session: &str, entry: Value) {
        for s in self.sessions.values_mut() {
            if s.live.as_ref().map(|l| l.page.sid == cdp_session).unwrap_or(false) {
                s.console.push_back(entry); while s.console.len() > CONSOLE_MAX { s.console.pop_front(); }
                return;
            }
        }
    }
}

impl Session {
    fn saved_url_or_live(&self) -> String { self.saved_url.clone() }
}

pub fn idle_sleep() -> Duration { Duration::from_secs(1) }
