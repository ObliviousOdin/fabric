//! Backend bridge: a plain OS thread running a small tokio runtime that owns
//! the `/api/ws` WebSocket and feeds parsed events into a crossbeam channel
//! the Bevy world drains once per frame.
//!
//! Connection recipe (mirrors the Electron desktop, see
//! `fabric_companion_core::gateway`):
//!
//! 1. Dial `ws://127.0.0.1:<port>/api/ws?token=<token>`.
//! 2. The server pushes a `gateway.ready` event immediately after accept.
//! 3. Bind a session: `session.create` (default — safe, never steals another
//!    surface's stream) or `session.resume` (opt-in; a resume re-binds the
//!    session's event transport to this socket).
//! 4. Optionally submit one prompt (`--prompt`) so a fresh session has a turn
//!    to animate.
//! 5. Forward this session's events into the channel until the socket dies,
//!    then reconnect with the desktop's backoff: `min(15s, 1s * 2^attempt)`.

use crossbeam_channel::Sender;
use fabric_companion_core::gateway::{parse_frame, request_frame, Event, Incoming};
use futures_util::{SinkExt, StreamExt};
use serde_json::json;
use tokio_tungstenite::tungstenite::Message;

/// What the bridge reports up to the Bevy world.
#[derive(Debug, Clone)]
pub enum BridgeUpdate {
    /// Connected and the session is bound. `running` is true when the
    /// resumed session already has a turn in flight.
    Bound { session_id: String, running: bool },
    /// An event for the bound session (already filtered).
    Event(Event),
    /// The connection dropped; the bridge is backing off and retrying.
    Disconnected,
}

/// How to bind a session once connected.
#[derive(Debug, Clone)]
pub enum SessionBinding {
    /// `session.create` — a fresh session owned by the companion.
    Create,
    /// `session.resume` of a stored session id, or the most recent session
    /// when None. NOTE: resuming re-binds that session's event stream to
    /// this socket — another attached surface (desktop, dashboard) stops
    /// receiving its events. Deliberate opt-in only.
    Resume(Option<String>),
}

#[derive(Debug, Clone)]
pub struct BridgeConfig {
    /// e.g. `ws://127.0.0.1:9119/api/ws?token=...` (token already appended).
    pub url: String,
    pub binding: SessionBinding,
    /// One prompt to submit after binding (fresh-session demo turn).
    pub prompt: Option<String>,
}

/// Spawn the bridge thread. Updates arrive on the returned channel's paired
/// receiver; the thread runs (and reconnects) for the life of the process.
pub fn spawn(config: BridgeConfig, tx: Sender<BridgeUpdate>) {
    std::thread::Builder::new()
        .name("fabric-companion-bridge".into())
        .spawn(move || {
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .expect("tokio runtime");
            runtime.block_on(run(config, tx));
        })
        .expect("spawn bridge thread");
}

async fn run(config: BridgeConfig, tx: Sender<BridgeUpdate>) {
    let mut attempt: u32 = 0;
    loop {
        match connect_once(&config, &tx).await {
            Ok(()) => attempt = 0,
            Err(err) => {
                log::warn!("bridge: connection failed: {err}");
            }
        }
        if tx.send(BridgeUpdate::Disconnected).is_err() {
            return; // Bevy side is gone; stop retrying.
        }
        let backoff_ms = 15_000u64.min(1000 * 2u64.pow(attempt.min(4)));
        attempt = attempt.saturating_add(1);
        tokio::time::sleep(std::time::Duration::from_millis(backoff_ms)).await;
    }
}

async fn connect_once(
    config: &BridgeConfig,
    tx: &Sender<BridgeUpdate>,
) -> Result<(), Box<dyn std::error::Error>> {
    let (ws, _resp) = tokio_tungstenite::connect_async(&config.url).await?;
    let (mut sink, mut stream) = ws.split();
    log::info!("bridge: connected");

    // Bind a session. Request ids are per-connection; low numbers are ours.
    let mut next_id: u64 = 1;
    let bind_id = next_id;
    let bind_frame = match &config.binding {
        SessionBinding::Create => request_frame(
            bind_id,
            "session.create",
            json!({"source": "companion", "close_on_disconnect": true}),
        ),
        SessionBinding::Resume(Some(sid)) => request_frame(
            bind_id,
            "session.resume",
            json!({"session_id": sid, "lazy": true}),
        ),
        SessionBinding::Resume(None) => request_frame(bind_id, "session.most_recent", json!({})),
    };
    next_id += 1;
    sink.send(Message::Text(bind_frame.into())).await?;

    let mut session_id: Option<String> = None;
    let mut resume_id: Option<u64> = None;

    while let Some(message) = stream.next().await {
        let message = message?;
        let text = match message {
            Message::Text(text) => text,
            Message::Ping(payload) => {
                sink.send(Message::Pong(payload)).await?;
                continue;
            }
            Message::Close(_) => break,
            _ => continue,
        };
        let Some(incoming) = parse_frame(&text) else {
            continue;
        };
        match incoming {
            Incoming::Response { id, result, error } => {
                if let Some(error) = error {
                    return Err(format!("rpc error: {error}").into());
                }
                let rid = id.as_u64();
                let result = result.unwrap_or_default();
                if rid == Some(bind_id) && matches!(config.binding, SessionBinding::Resume(None)) {
                    // session.most_recent answered — now resume that id.
                    let stored = result
                        .get("session_id")
                        .or_else(|| result.get("stored_session_id"))
                        .and_then(|v| v.as_str())
                        .ok_or("no session to resume — is there a stored session?")?;
                    let id = next_id;
                    next_id += 1;
                    resume_id = Some(id);
                    sink.send(Message::Text(
                        request_frame(
                            id,
                            "session.resume",
                            json!({"session_id": stored, "lazy": true}),
                        )
                        .into(),
                    ))
                    .await?;
                } else if rid == Some(bind_id) || (rid.is_some() && rid == resume_id) {
                    let sid =
                        bound_session_id(&result).ok_or("bind response carried no session_id")?;
                    // session.resume reports whether a turn is mid-flight so
                    // the pet can show activity immediately.
                    let running = result
                        .get("running")
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false);
                    session_id = Some(sid.clone());
                    on_bound(&mut sink, &mut next_id, config, sid, running, tx).await?;
                }
            }
            Incoming::Event(event) => {
                // Session-scoped events for other sessions are not ours;
                // unscoped (global) events pass through for the tracker to
                // ignore or use (gateway.ready has no session).
                let ours = event.session_id.is_empty()
                    || session_id.as_deref() == Some(event.session_id.as_str());
                if ours && tx.send(BridgeUpdate::Event(event)).is_err() {
                    return Ok(()); // receiver gone — shut down quietly
                }
            }
        }
    }
    Ok(())
}

fn bound_session_id(result: &serde_json::Value) -> Option<String> {
    result
        .get("session_id")
        .and_then(|v| v.as_str())
        .map(str::to_owned)
}

async fn on_bound<S>(
    sink: &mut S,
    next_id: &mut u64,
    config: &BridgeConfig,
    session_id: String,
    running: bool,
    tx: &Sender<BridgeUpdate>,
) -> Result<(), Box<dyn std::error::Error>>
where
    S: SinkExt<Message> + Unpin,
    S::Error: std::error::Error + 'static,
{
    let _ = tx.send(BridgeUpdate::Bound {
        session_id: session_id.clone(),
        running,
    });
    if let Some(prompt) = &config.prompt {
        let id = *next_id;
        *next_id += 1;
        sink.send(Message::Text(
            request_frame(
                id,
                "prompt.submit",
                json!({"session_id": session_id, "text": prompt}),
            )
            .into(),
        ))
        .await?;
    }
    Ok(())
}
