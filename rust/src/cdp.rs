//! Minimal Chrome DevTools Protocol client over a websocket: request/response by id, events by
//! (sessionId, method) to subscribers. One connection per browser process.
use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use tokio::sync::{broadcast, mpsc, oneshot};
use tokio_tungstenite::tungstenite::Message;

#[derive(Clone, Debug)]
pub struct Event {
    pub session_id: Option<String>,
    pub method: String,
    pub params: Value,
}

#[derive(Clone)]
pub struct Cdp {
    tx: mpsc::UnboundedSender<String>,
    pending: Arc<Mutex<HashMap<u64, oneshot::Sender<Result<Value, String>>>>>,
    next_id: Arc<AtomicU64>,
    events: broadcast::Sender<Event>,
}

impl Cdp {
    pub async fn connect(ws_url: &str) -> Result<Cdp, String> {
        let (ws, _) = tokio_tungstenite::connect_async(ws_url).await.map_err(|e| format!("ws connect: {e}"))?;
        let (mut sink, mut stream) = ws.split();
        let (tx, mut rx) = mpsc::unbounded_channel::<String>();
        let pending: Arc<Mutex<HashMap<u64, oneshot::Sender<Result<Value, String>>>>> = Arc::new(Mutex::new(HashMap::new()));
        let (events, _) = broadcast::channel::<Event>(4096);
        tokio::spawn(async move {
            while let Some(msg) = rx.recv().await {
                if sink.send(Message::Text(msg)).await.is_err() { break; }
            }
        });
        let p2 = pending.clone();
        let ev2 = events.clone();
        tokio::spawn(async move {
            while let Some(Ok(msg)) = stream.next().await {
                let txt = match msg { Message::Text(t) => t, _ => continue };
                let v: Value = match serde_json::from_str(&txt) { Ok(v) => v, Err(_) => continue };
                if let Some(id) = v.get("id").and_then(|i| i.as_u64()) {
                    if let Some(s) = p2.lock().unwrap().remove(&id) {
                        let r = if let Some(e) = v.get("error") { Err(e.get("message").and_then(|m| m.as_str()).unwrap_or("cdp error").to_string()) } else { Ok(v.get("result").cloned().unwrap_or(Value::Null)) };
                        let _ = s.send(r);
                    }
                } else if let Some(m) = v.get("method").and_then(|m| m.as_str()) {
                    let _ = ev2.send(Event { session_id: v.get("sessionId").and_then(|s| s.as_str()).map(String::from), method: m.to_string(), params: v.get("params").cloned().unwrap_or(Value::Null) });
                }
            }
            // connection closed: fail all pending
            for (_, s) in p2.lock().unwrap().drain() { let _ = s.send(Err("cdp connection closed".into())); }
        });
        Ok(Cdp { tx, pending, next_id: Arc::new(AtomicU64::new(1)), events })
    }

    pub async fn send(&self, session: Option<&str>, method: &str, params: Value) -> Result<Value, String> {
        let id = self.next_id.fetch_add(1, Ordering::SeqCst);
        let (s, r) = oneshot::channel();
        self.pending.lock().unwrap().insert(id, s);
        let mut msg = json!({"id": id, "method": method, "params": params});
        if let Some(sid) = session { msg["sessionId"] = json!(sid); }
        self.tx.send(msg.to_string()).map_err(|_| "cdp send: connection closed".to_string())?;
        // Per-command timeout. Configurable via BROWSER_CDP_TIMEOUT_MS so a wedged renderer fails fast
        // (default 60s, unchanged). On timeout the pending entry is dropped and the caller gets an error
        // it can act on (server.rs then attempts a reload-based recovery).
        let timeout_ms: u64 = std::env::var("BROWSER_CDP_TIMEOUT_MS").ok().and_then(|v| v.parse().ok()).filter(|&v| v > 0).unwrap_or(60_000);
        match tokio::time::timeout(std::time::Duration::from_millis(timeout_ms), r).await {
            Ok(Ok(v)) => v,
            Ok(Err(_)) => Err("cdp: response channel dropped".into()),
            Err(_) => { self.pending.lock().unwrap().remove(&id); Err(format!("cdp: {method} timed out")) }
        }
    }

    pub fn subscribe(&self) -> broadcast::Receiver<Event> { self.events.subscribe() }

    pub fn is_alive(&self) -> bool { !self.tx.is_closed() }
}
